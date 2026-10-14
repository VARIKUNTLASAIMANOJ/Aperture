"use client";

import { SelectField, TextField } from "@/components/ui/Field";
import type { Draft, Errors } from "@/lib/form";

interface Props {
  draft: Draft;
  errors: Errors;
  set: <K extends keyof Draft>(k: K, v: Draft[K]) => void;
}

const DEPARTMENTS = [
  "Engineering", "Product", "Design", "Data", "Sales",
  "Marketing", "Finance", "People", "Operations", "Legal",
].map((d) => ({ value: d, label: d }));

export function IdentityStep({ draft, errors, set }: Props) {
  return (
    <div className="space-y-5">
      <TextField
        label="Candidate name" required
        value={draft.candidate_name}
        onChange={(v) => set("candidate_name", v)}
        error={errors.candidate_name}
        placeholder="Ada Lovelace"
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          label="Candidate email" required type="email" inputMode="email"
          value={draft.candidate_email}
          onChange={(v) => set("candidate_email", v)}
          error={errors.candidate_email}
          placeholder="ada@example.com"
          hint="Offer or rejection notice is delivered here."
        />
        <TextField
          label="Reference ID" required
          value={draft.candidate_id}
          onChange={(v) => set("candidate_id", v)}
          error={errors.candidate_id}
          placeholder="CAND-2041"
          hint="Your ATS identifier. Appears in the audit trail."
        />
      </div>

      {/* The number the voice follow-up dials. Captured here and nowhere else:
          the agent reads it from this candidate's own record, so a call can
          never reach a number resolved by name or email. */}
      <TextField
        label="Candidate phone" type="tel" inputMode="tel"
        value={draft.candidate_phone}
        onChange={(v) => set("candidate_phone", v)}
        error={errors.candidate_phone}
        placeholder="+91 98765 43210"
        hint="Optional. Used only for the automated offer follow-up call — leave blank to skip calling this candidate."
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          label="Role title" required
          value={draft.role_title}
          onChange={(v) => set("role_title", v)}
          error={errors.role_title}
          placeholder="Senior Platform Engineer"
        />
        <SelectField
          label="Department" required
          value={draft.department}
          onChange={(v) => set("department", v)}
          error={errors.department}
          options={[{ value: "", label: "Select a department…" }, ...DEPARTMENTS]}
        />
      </div>

      <TextField
        label="Hiring manager email" required type="email" inputMode="email"
        value={draft.hiring_manager_email}
        onChange={(v) => set("hiring_manager_email", v)}
        error={errors.hiring_manager_email}
        placeholder="manager@company.com"
      />
    </div>
  );
}
