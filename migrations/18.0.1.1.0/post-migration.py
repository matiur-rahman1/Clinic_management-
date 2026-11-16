def migrate(cr, version):
    """Medicine became a plain catalog. Copy the old medicine name onto every existing
    prescription line so no history is lost, and fill the new Strength/Form from the catalog."""
    cr.execute("""
        UPDATE clinic_prescription_line l
           SET drug_name = m.name
          FROM clinic_medicine m
         WHERE l.medicine_id = m.id
           AND (l.drug_name IS NULL OR l.drug_name = '')
    """)
