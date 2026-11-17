/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    Component,
    useState,
    onWillStart,
    onMounted,
    onWillUnmount,
    onWillUpdateProps,
} from "@odoo/owl";

const STATE_COLORS = {
    draft: "#94a3b8",
    confirmed: "#3b82f6",
    in_progress: "#f59e0b",
    done: "#10b981",
    cancelled: "#ef4444",
};
const CONFETTI_COLORS = ["#7c3aed", "#f59e0b", "#10b981", "#3b82f6", "#ef4444"];

/** Number that counts up smoothly whenever its value changes. */
class CountUp extends Component {
    static template = "clinic_management.CountUp";
    static props = { value: Number, decimals: { type: Number, optional: true } };

    setup() {
        this.state = useState({ shown: 0 });
        this.raf = null;
        onMounted(() => this.animate(0, this.props.value));
        onWillUpdateProps((next) => {
            if (next.value !== this.props.value) {
                this.animate(this.state.shown, next.value);
            }
        });
        onWillUnmount(() => cancelAnimationFrame(this.raf));
    }

    animate(from, to) {
        cancelAnimationFrame(this.raf);
        const start = performance.now();
        const duration = 1100;
        const step = (now) => {
            const p = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - p, 3);
            this.state.shown = from + (to - from) * eased;
            if (p < 1) {
                this.raf = requestAnimationFrame(step);
            }
        };
        this.raf = requestAnimationFrame(step);
    }

    get text() {
        const d = this.props.decimals || 0;
        return this.state.shown.toLocaleString(undefined, {
            minimumFractionDigits: d,
            maximumFractionDigits: d,
        });
    }
}

export class ClinicDashboard extends Component {
    static template = "clinic_management.Dashboard";
    static components = { CountUp };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            data: null,
            animate: false,
            refreshing: false,
            updated: "",
            celebrate: false,
        });
        this.confetti = Array.from({ length: 28 }, (_, i) => ({
            left: Math.round(Math.random() * 100),
            delay: (Math.random() * 1.2).toFixed(2),
            dur: (2 + Math.random() * 2).toFixed(2),
            color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
        }));

        onWillStart(() => this.load());
        onMounted(() => {
            // Let the first frame render at 0, then grow bars / draw the donut
            this.animTimer = setTimeout(() => (this.state.animate = true), 150);
            this.timer = setInterval(() => this.load(), 30000);
        });
        onWillUnmount(() => {
            clearInterval(this.timer);
            clearTimeout(this.animTimer);
            clearTimeout(this.confettiTimer);
        });
    }

    async load() {
        this.state.refreshing = true;
        try {
            const first = !this.state.data;
            const data = await this.orm.call("clinic.appointment", "get_dashboard_data", []);
            this.state.data = data;
            this.state.updated = new Date().toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
            });
            const k = data.kpis;
            if (first && k.today_total > 0 && k.today_done === k.today_total) {
                this.state.celebrate = true;
                this.confettiTimer = setTimeout(() => (this.state.celebrate = false), 5500);
            }
        } catch (e) {
            console.error("Clinic dashboard failed to load", e);
        } finally {
            this.state.refreshing = false;
        }
    }

    fmt(n) {
        return Math.round(n || 0).toLocaleString();
    }

    // ---------- derived data ----------
    get greeting() {
        const h = this.state.data.hour;
        const part = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
        return `${part}, ${this.state.data.user}`;
    }

    get cards() {
        const k = this.state.data.kpis;
        const cur = this.state.data.currency;
        return [
            { key: "today", label: "Today's Appointments", value: k.today_total, icon: "fa-calendar-check-o", tone: "violet", sub: `${k.today_done} completed` },
            { key: "queue", label: "Waiting in Queue", value: k.queue_waiting, icon: "fa-users", tone: "amber", sub: `${k.queue_active} in consultation` },
            { key: "patients", label: "Total Patients", value: k.patients, icon: "fa-heartbeat", tone: "teal", sub: `${k.new_patients_month} new this month` },
            { key: "revenue", label: "Revenue (This Month)", value: k.revenue, icon: "fa-money", tone: "green", sub: `${cur} ${this.fmt(k.paid)} collected` },
            { key: "followups", label: "Follow-ups (7 days)", value: k.followups, icon: "fa-repeat", tone: "blue", sub: k.followups ? "Patients to call back" : "Nothing due" },
        ];
    }

    get weekBars() {
        const week = this.state.data.week;
        const max = Math.max(...week.map((b) => b.count), 1);
        return week.map((b) => ({
            ...b,
            pct: b.count ? Math.max((b.count / max) * 100, 8) : 1,
        }));
    }

    get donut() {
        const R = 52;
        const C = 2 * Math.PI * R;
        const items = this.state.data.status.filter((i) => i.count > 0);
        const total = items.reduce((s, i) => s + i.count, 0);
        let offset = 0;
        const segs = items.map((i) => {
            const len = total ? (i.count / total) * C : 0;
            const seg = {
                ...i,
                color: STATE_COLORS[i.key] || "#94a3b8",
                dash: Math.max(len - 3, 0),
                offset,
                pct: total ? Math.round((i.count / total) * 100) : 0,
            };
            offset += len;
            return seg;
        });
        return { total, segs, C, R };
    }

    get doctorBars() {
        const docs = this.state.data.doctors;
        const max = Math.max(...docs.map((d) => d.count), 1);
        return docs.map((d) => ({ ...d, pct: (d.count / max) * 100 }));
    }

    // ---------- interactions ----------
    onCardMove(ev) {
        const el = ev.currentTarget;
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${ev.clientX - r.left}px`);
        el.style.setProperty("--my", `${ev.clientY - r.top}px`);
    }

    openCard(key) {
        const r = this.state.data.range;
        const map = {
            today: { name: "Today's Appointments", res_model: "clinic.appointment", domain: [["appointment_date", ">=", r.from], ["appointment_date", "<", r.to]] },
            queue: { name: "Queue", res_model: "clinic.queue", domain: [["state", "in", ["waiting", "in_consultation"]]] },
            patients: { name: "Patients", res_model: "clinic.patient", domain: [] },
            revenue: { name: "Clinic Invoices", res_model: "account.move", domain: [["clinic_appointment_id", "!=", false]] },
            followups: { name: "Follow-ups due", res_model: "clinic.appointment", domain: [["follow_up_date", ">=", r.fu_from], ["follow_up_date", "<=", r.fu_to]] },
        };
        this.actionService.doAction({
            type: "ir.actions.act_window",
            ...map[key],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openRecord(model, id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    newRecord(model, name) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openTvDisplay() {
        window.open("/clinic/tv", "_blank");
    }
}

registry.category("actions").add("clinic_dashboard", ClinicDashboard);