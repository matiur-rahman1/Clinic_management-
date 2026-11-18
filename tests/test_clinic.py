from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'clinic_management')
class TestClinicManagement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doctor = cls.env['clinic.doctor'].create({
            'name': 'Test Doctor', 'specialty': 'general', 'consultation_fee': 500.0,
        })
        cls.patient = cls.env['clinic.patient'].create({
            'name': 'Test Patient', 'email': 'patient@example.com',
            'allergies': 'Penicillin, Peanuts',
        })
        cls.start = fields.Datetime.now() + timedelta(days=2)

    def _appointment(self, **kw):
        vals = {
            'patient_id': self.patient.id,
            'doctor_id': self.doctor.id,
            'appointment_date': self.start,
        }
        vals.update(kw)
        return self.env['clinic.appointment'].create(vals)

    def test_01_sequences_and_partner(self):
        self.assertNotEqual(self.patient.patient_id, 'New')
        self.assertTrue(self.patient.partner_id, "A billing contact must be created automatically.")
        appt = self._appointment()
        self.assertNotEqual(appt.name, 'New')

    def test_02_doctor_overlap_is_blocked(self):
        self._appointment()
        with self.assertRaises(ValidationError):
            self._appointment(appointment_date=self.start + timedelta(minutes=10))

    def test_03_workflow_and_queue(self):
        appt = self._appointment()
        appt.action_confirm()
        self.assertEqual(appt.state, 'confirmed')
        appt.action_start()
        self.assertEqual(appt.state, 'in_progress')
        self.assertEqual(appt.queue_ids.state, 'in_consultation')
        appt.action_done()
        self.assertEqual(appt.state, 'done')
        self.assertEqual(appt.queue_ids.state, 'done')

    def test_04_bmi_and_vital_alerts(self):
        appt = self._appointment(
            weight=90, height=170, bp_systolic=150, bp_diastolic=95,
            temperature=101.2, spo2=92, pulse=110)
        self.assertAlmostEqual(appt.bmi, 31.1, places=1)
        self.assertEqual(appt.bmi_status, 'obese')
        self.assertEqual(appt.bp_display, '150/95 mmHg')
        for expected in ('Hypertensive', 'Fever', 'Low SpO', 'Tachycardia'):
            self.assertIn(expected, appt.vital_alert)

    def test_05_normal_vitals_have_no_alert(self):
        appt = self._appointment(
            weight=65, height=170, bp_systolic=118, bp_diastolic=76,
            temperature=98.4, spo2=98, pulse=72)
        self.assertEqual(appt.bmi_status, 'normal')
        self.assertFalse(appt.vital_alert)

    def test_06_allergy_guard(self):
        appt = self._appointment()
        self.env['clinic.prescription.line'].create({
            'appointment_id': appt.id, 'drug_name': 'Penicillin V', 'dosage': '1+1+1'})
        self.assertIn('Penicillin', appt.allergy_warning)
        safe = self._appointment(appointment_date=self.start + timedelta(hours=3))
        self.env['clinic.prescription.line'].create({
            'appointment_id': safe.id, 'drug_name': 'Paracetamol', 'dosage': '1+0+1'})
        self.assertFalse(safe.allergy_warning)

    def test_07_rx_template_apply_and_save(self):
        tmpl = self.env.ref('clinic_management.rx_template_viral_fever')
        appt = self._appointment()
        appt.rx_template_id = tmpl
        appt._onchange_rx_template_id()
        self.assertEqual(len(appt.prescription_ids), len(tmpl.line_ids))
        self.assertTrue(appt.follow_up_date)
        before = self.env['clinic.rx.template'].search_count([])
        appt.action_save_as_rx_template()
        self.assertEqual(self.env['clinic.rx.template'].search_count([]), before + 1)

    def test_08_dashboard_and_tv_payload(self):
        data = self.env['clinic.appointment'].get_dashboard_data()
        for key in ('kpis', 'week', 'status', 'doctors', 'schedule', 'queue', 'followups'):
            self.assertIn(key, data)

    def test_09_available_slots_respect_bookings(self):
        day = self.start.date()
        self.env['clinic.doctor.schedule'].create({
            'doctor_id': self.doctor.id, 'weekday': str(day.weekday()),
            'start_time': 9.0, 'end_time': 12.0, 'slot_duration': 0.5, 'max_patients': 6,
        })
        tz = self.env['clinic.appointment']._get_booking_tz()
        slots = self.doctor.get_available_slots(day, tz)
        self.assertTrue(slots, "A scheduled day must expose free slots.")
        booked = slots[0]
        self._appointment(appointment_date=booked['utc'], duration=0.5)
        remaining = [s['utc'] for s in self.doctor.get_available_slots(day, tz)]
        self.assertNotIn(booked['utc'], remaining)
