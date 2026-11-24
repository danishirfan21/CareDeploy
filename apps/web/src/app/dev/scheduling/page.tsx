"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL } from "@/lib/api/client";
import {
  PageHeader,
  primaryBtn,
  secondaryBtn,
  inputCls,
} from "@/components/ui";

/**
 * DEVELOPMENT / TEST ONLY. Exercises the M2 scheduling API against synthetic patients.
 * Not a patient portal and not part of the product navigation.
 */

type Clinic = { id: string; name: string };
type PatientHit = { id: string; full_name: string };
type SType = {
  id: string;
  name: string;
  duration_minutes: number;
  requires_human_escalation: boolean;
};
type Info = { timezone: string; appointment_types: SType[] };
type Slot = { start_at: string; end_at: string };
type Appt = {
  id: string;
  type_name: string;
  start_at: string;
  end_at: string;
  status: string;
};
type Proposal = {
  id: string;
  status: string;
  summary: string;
  confirmation_token: string | null;
};
type ApiErr = { code: string; message: string };

async function call<T>(
  clinicId: string,
  path: string,
  init: RequestInit & { token?: string; key?: string } = {},
): Promise<{ ok: true; data: T } | { ok: false; error: ApiErr }> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body) headers["Content-Type"] = "application/json";
  if (init.token) headers.Authorization = `Bearer ${init.token}`;
  if (init.key) headers["Idempotency-Key"] = init.key;
  const res = await fetch(`${API_BASE_URL}/api/clinics/${clinicId}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const e = (body as { error?: ApiErr } | null)?.error;
    return {
      ok: false,
      error: e ?? { code: "http_" + res.status, message: "Request failed" },
    };
  }
  return { ok: true, data: body as T };
}

export default function DevScheduling() {
  const [clinics, setClinics] = useState<Clinic[]>([]);
  const [clinicId, setClinicId] = useState("");
  const [info, setInfo] = useState<Info | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<PatientHit[]>([]);
  const [patient, setPatient] = useState<PatientHit | null>(null);
  const [dob, setDob] = useState("");
  const [last4, setLast4] = useState("");
  const [token, setToken] = useState("");
  const [typeId, setTypeId] = useState("");
  const [date, setDate] = useState("");
  const [slots, setSlots] = useState<Slot[]>([]);
  const [slot, setSlot] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [appts, setAppts] = useState<Appt[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const fail = (e: ApiErr) => {
    setMessage("");
    setError(`${e.code}: ${e.message}`);
  };

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/clinics`)
      .then((r) => r.json())
      .then((c: Clinic[]) => setClinics(c))
      .catch(() => setError("Could not load clinics"));
  }, []);

  const reset = () => {
    setInfo(null);
    setHits([]);
    setPatient(null);
    setToken("");
    setSlots([]);
    setSlot("");
    setProposal(null);
    setConfirmed(false);
    setAppts([]);
    setMessage("");
    setError("");
  };

  const pickClinic = async (id: string) => {
    reset();
    setClinicId(id);
    if (!id) return;
    const r = await call<Info>(id, "/scheduling");
    if (r.ok) {
      setInfo(r.data);
      setTypeId(r.data.appointment_types[0]?.id ?? "");
    } else fail(r.error);
  };

  const search = async () => {
    const r = await call<PatientHit[]>(
      clinicId,
      `/patients?name=${encodeURIComponent(query)}`,
    );
    if (r.ok) setHits(r.data);
    else fail(r.error);
  };

  const verify = async () => {
    if (!patient) return;
    setError("");
    const r = await call<{ authorization_token: string }>(
      clinicId,
      `/patients/${patient.id}/verify`,
      {
        method: "POST",
        body: JSON.stringify({ date_of_birth: dob, phone_last4: last4 }),
      },
    );
    if (r.ok) {
      setToken(r.data.authorization_token);
      setMessage("Verified (simulated). Authorization issued by the server.");
      await loadAppts(r.data.authorization_token);
    } else fail(r.error);
  };

  const loadAppts = async (tok = token) => {
    if (!patient) return;
    const r = await call<Appt[]>(
      clinicId,
      `/patients/${patient.id}/appointments`,
      { token: tok },
    );
    if (r.ok) setAppts(r.data);
    else fail(r.error);
  };

  const findSlots = async () => {
    setProposal(null);
    setConfirmed(false);
    const r = await call<{ slots: Slot[] }>(
      clinicId,
      `/availability?appointment_type_id=${typeId}&date_from=${date}&limit=24`,
    );
    if (r.ok) {
      setSlots(r.data.slots);
      setSlot(r.data.slots[0]?.start_at ?? "");
    } else fail(r.error);
  };

  const propose = async () => {
    setError("");
    const r = await call<Proposal>(clinicId, "/proposals", {
      method: "POST",
      token,
      body: JSON.stringify({
        action: "book",
        appointment_type_id: typeId,
        start_at: slot,
      }),
    });
    if (r.ok) {
      setProposal(r.data);
      setConfirmed(false);
    } else fail(r.error);
  };

  const confirm = async () => {
    if (!proposal?.confirmation_token) return;
    const r = await call<Proposal>(
      clinicId,
      `/proposals/${proposal.id}/confirm`,
      {
        method: "POST",
        token,
        body: JSON.stringify({
          confirmation_token: proposal.confirmation_token,
        }),
      },
    );
    if (r.ok) setConfirmed(true);
    else fail(r.error);
  };

  const book = async () => {
    if (!proposal) return;
    const r = await call<{ appointment: Appt }>(clinicId, "/appointments", {
      method: "POST",
      token,
      key: `dev-${crypto.randomUUID()}`,
      body: JSON.stringify({
        proposal_id: proposal.id,
        appointment_type_id: typeId,
        start_at: slot,
      }),
    });
    if (r.ok) {
      setMessage(`Booked ${r.data.appointment.type_name}`);
      setProposal(null);
      setConfirmed(false);
      await loadAppts();
    } else fail(r.error);
  };

  const cancel = async (a: Appt) => {
    const p = await call<Proposal>(clinicId, "/proposals", {
      method: "POST",
      token,
      body: JSON.stringify({ action: "cancel", appointment_id: a.id }),
    });
    if (!p.ok) return fail(p.error);
    const c = await call<Proposal>(
      clinicId,
      `/proposals/${p.data.id}/confirm`,
      {
        method: "POST",
        token,
        body: JSON.stringify({ confirmation_token: p.data.confirmation_token }),
      },
    );
    if (!c.ok) return fail(c.error);
    const r = await call<{ appointment: Appt }>(
      clinicId,
      `/appointments/${a.id}/cancel`,
      {
        method: "POST",
        token,
        key: `dev-${crypto.randomUUID()}`,
        body: JSON.stringify({ proposal_id: p.data.id }),
      },
    );
    if (r.ok) {
      setMessage("Appointment cancelled");
      await loadAppts();
    } else fail(r.error);
  };

  const fmt = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      timeZone: info?.timezone,
      dateStyle: "medium",
      timeStyle: "short",
    });

  return (
    <div data-testid="dev-scheduling">
      <PageHeader
        title="Scheduling test console"
        subtitle="Development and test only. Synthetic patients, simulated verification. Not a patient portal."
      />
      <div className="space-y-6 text-sm">
        {error && (
          <p
            role="alert"
            data-testid="dev-error"
            className="rounded-lg bg-red-50 p-3 text-red-800"
          >
            {error}
          </p>
        )}
        {message && (
          <p
            role="status"
            data-testid="dev-status"
            className="rounded-lg bg-green-50 p-3 text-green-800"
          >
            {message}
          </p>
        )}

        <section className="space-y-2">
          <h2 className="font-medium">1. Clinic</h2>
          <select
            aria-label="Clinic"
            className={inputCls}
            value={clinicId}
            onChange={(e) => void pickClinic(e.target.value)}
          >
            <option value="">Select a clinic…</option>
            {clinics.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          {info && <p className="text-muted">Time zone: {info.timezone}</p>}
        </section>

        {info && (
          <section className="space-y-2">
            <h2 className="font-medium">2. Synthetic patient</h2>
            <div className="flex gap-2">
              <input
                aria-label="Patient name search"
                className={inputCls}
                placeholder="Search by name (2+ letters)"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <button
                className={secondaryBtn}
                onClick={() => void search()}
                disabled={query.length < 2}
              >
                Search
              </button>
            </div>
            <ul>
              {hits.map((h) => (
                <li key={h.id}>
                  <button
                    className="text-accent hover:underline"
                    onClick={() => {
                      setPatient(h);
                      setToken("");
                    }}
                  >
                    {h.full_name}
                  </button>
                </li>
              ))}
            </ul>
            {patient && (
              <div className="flex flex-wrap items-end gap-2">
                <span className="font-medium">{patient.full_name}</span>
                <input
                  aria-label="Date of birth"
                  type="date"
                  className={inputCls + " max-w-44"}
                  value={dob}
                  onChange={(e) => setDob(e.target.value)}
                />
                <input
                  aria-label="Phone last 4"
                  className={inputCls + " max-w-32"}
                  placeholder="Phone last 4"
                  maxLength={4}
                  value={last4}
                  onChange={(e) => setLast4(e.target.value)}
                />
                <button className={primaryBtn} onClick={() => void verify()}>
                  Verify
                </button>
              </div>
            )}
          </section>
        )}

        {token && info && (
          <section className="space-y-2">
            <h2 className="font-medium">3. Availability and booking</h2>
            <div className="flex flex-wrap items-end gap-2">
              <select
                aria-label="Appointment type"
                className={inputCls + " max-w-64"}
                value={typeId}
                onChange={(e) => setTypeId(e.target.value)}
              >
                {info.appointment_types.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.duration_minutes} min)
                  </option>
                ))}
              </select>
              <input
                aria-label="Date"
                type="date"
                className={inputCls + " max-w-44"}
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
              <button
                className={secondaryBtn}
                disabled={!date}
                onClick={() => void findSlots()}
              >
                Show availability
              </button>
            </div>
            {slots.length > 0 && (
              <div className="flex flex-wrap items-end gap-2">
                <select
                  aria-label="Slot"
                  className={inputCls + " max-w-64"}
                  value={slot}
                  onChange={(e) => setSlot(e.target.value)}
                >
                  {slots.map((s) => (
                    <option key={s.start_at} value={s.start_at}>
                      {fmt(s.start_at)}
                    </option>
                  ))}
                </select>
                <button className={primaryBtn} onClick={() => void propose()}>
                  Propose booking
                </button>
              </div>
            )}
            {proposal && (
              <div className="rounded-lg border border-line p-3">
                <p data-testid="proposal-summary">{proposal.summary}</p>
                <p className="text-muted">Status: {proposal.status}</p>
                <div className="mt-2 flex gap-2">
                  {!confirmed ? (
                    <button
                      className={primaryBtn}
                      onClick={() => void confirm()}
                    >
                      Confirm
                    </button>
                  ) : (
                    <button className={primaryBtn} onClick={() => void book()}>
                      Book appointment
                    </button>
                  )}
                </div>
              </div>
            )}
          </section>
        )}

        {token && (
          <section className="space-y-2">
            <h2 className="font-medium">4. Patient appointments</h2>
            {appts.length === 0 ? (
              <p className="text-muted">No scheduled appointments.</p>
            ) : (
              <ul className="divide-y divide-line rounded-lg border border-line">
                {appts.map((a) => (
                  <li
                    key={a.id}
                    data-testid="appointment-row"
                    className="flex items-center justify-between p-3"
                  >
                    <span>
                      {a.type_name} · {fmt(a.start_at)} · {a.status}
                    </span>
                    <button
                      className={secondaryBtn}
                      onClick={() => void cancel(a)}
                    >
                      Cancel
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
