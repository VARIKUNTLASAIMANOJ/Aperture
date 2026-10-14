"use client";

import { motion } from "framer-motion";
import { useId } from "react";

import { fieldItem } from "@/lib/motion";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { IconAlert } from "./Icons";

interface BaseProps {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  className?: string;
}

/**
 * Label is always rendered and always visible.
 * ux-guidelines "Form Labels" (severity High) — Don't: "Placeholder-only
 * inputs". Placeholders here are format examples, never the field name.
 *
 * Errors render adjacent to their own field and are wired via
 * aria-describedby + aria-invalid, not just colour.
 */
function useFieldIds(error?: string, hint?: string) {
  const id = useId();
  const errorId = error ? `${id}-error` : undefined;
  const hintId = hint ? `${id}-hint` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  return { id, errorId, hintId, describedBy };
}

const shell =
  "w-full rounded-xl bg-fill border px-4 py-3 text-[15px] text-fg " +
  "placeholder:text-fg-faint transition-colors duration-[--t-hover] " +
  "focus:bg-fill-strong focus:border-signal/60 hover:border-line-strong";

function Shell({
  label, hint, error, required, children, id, errorId, hintId,
}: BaseProps & {
  children: React.ReactNode;
  id: string;
  errorId?: string;
  hintId?: string;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div variants={fieldItem(reduced)} className="space-y-1.5">
      <label
        htmlFor={id}
        className="flex items-baseline gap-1.5 text-body font-medium text-fg-muted"
      >
        {label}
        {required && (
          <span className="text-signal" aria-hidden="true">
            *
          </span>
        )}
        {required && <span className="sr-only">(required)</span>}
      </label>
      {children}
      {hint && !error && (
        <p id={hintId} className="text-xs leading-relaxed text-fg-faint">
          {hint}
        </p>
      )}
      {error && (
        <p
          id={errorId}
          role="alert"
          className="flex items-center gap-1.5 text-xs font-medium text-alarm"
        >
          <IconAlert className="h-3.5 w-3.5 shrink-0" />
          {error}
        </p>
      )}
    </motion.div>
  );
}

interface TextFieldProps extends BaseProps {
  value: string;
  onChange: (v: string) => void;
  type?: "text" | "email" | "date" | "number" | "tel";
  placeholder?: string;
  min?: string | number;
  step?: string | number;
  inputMode?: "text" | "email" | "numeric" | "decimal" | "tel";
}

export function TextField({
  value, onChange, type = "text", placeholder, min, step, inputMode, ...rest
}: TextFieldProps) {
  const { id, errorId, hintId, describedBy } = useFieldIds(rest.error, rest.hint);
  return (
    <Shell {...rest} id={id} errorId={errorId} hintId={hintId}>
      <input
        id={id}
        type={type}
        value={value}
        min={min}
        step={step}
        inputMode={inputMode}
        placeholder={placeholder}
        aria-invalid={rest.error ? true : undefined}
        aria-describedby={describedBy}
        aria-required={rest.required || undefined}
        onChange={(e) => onChange(e.target.value)}
        className={`${shell} ${
          rest.error ? "border-alarm/60" : "border-line"
        }`}
      />
    </Shell>
  );
}

interface SelectFieldProps extends BaseProps {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}

export function SelectField({
  value, onChange, options, ...rest
}: SelectFieldProps) {
  const { id, errorId, hintId, describedBy } = useFieldIds(rest.error, rest.hint);
  return (
    <Shell {...rest} id={id} errorId={errorId} hintId={hintId}>
      <div className="relative">
        <select
          id={id}
          value={value}
          aria-invalid={rest.error ? true : undefined}
          aria-describedby={describedBy}
          onChange={(e) => onChange(e.target.value)}
          className={`${shell} cursor-pointer appearance-none pr-10 ${
            rest.error ? "border-alarm/60" : "border-line"
          }`}
        >
          {options.map((o) => (
            // Options render in the OS menu, which ignores page styling —
            // set an explicit dark background so the text stays readable.
            <option key={o.value} value={o.value} className="bg-abyss text-fg">
              {o.label}
            </option>
          ))}
        </select>
        <svg
          className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted"
          viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </div>
    </Shell>
  );
}
