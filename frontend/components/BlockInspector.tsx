"use client";

import { useMemo, useState } from "react";
import type { BlockSpec, WorkflowStep } from "@/lib/api";

type Props = {
  step: WorkflowStep;
  stepIndex: number;
  block: BlockSpec | undefined;
  editable: boolean;
  onSave: (newParams: Record<string, unknown>) => void;
  onClose: () => void;
};

type ParamSpec = {
  type?: string;
  description?: string;
  required?: boolean;
  enum?: unknown[];
  items?: { type?: string };
};

function specOf(value: unknown): ParamSpec {
  return (value && typeof value === "object" ? (value as ParamSpec) : {});
}

function inferType(spec: ParamSpec, current: unknown): string {
  if (spec.type) return spec.type;
  if (typeof current === "boolean") return "boolean";
  if (typeof current === "number") return "number";
  if (Array.isArray(current)) return "array";
  if (current && typeof current === "object") return "object";
  return "string";
}

export function BlockInspector({
  step,
  stepIndex,
  block,
  editable,
  onSave,
  onClose,
}: Props) {
  const paramSchema = useMemo(
    () => (block?.params ?? {}) as Record<string, unknown>,
    [block]
  );

  const [draft, setDraft] = useState<Record<string, unknown>>({ ...step.params });
  const [jsonText, setJsonText] = useState<Record<string, string>>({});
  const [parseErrors, setParseErrors] = useState<Record<string, string>>({});

  const dirty = JSON.stringify(draft) !== JSON.stringify(step.params);

  function setField(name: string, value: unknown) {
    setDraft((d) => ({ ...d, [name]: value }));
  }

  function setJsonField(name: string, raw: string, kind: "array" | "object") {
    setJsonText((t) => ({ ...t, [name]: raw }));
    if (!raw.trim()) {
      setField(name, kind === "array" ? [] : {});
      setParseErrors((e) => ({ ...e, [name]: "" }));
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      setField(name, parsed);
      setParseErrors((e) => ({ ...e, [name]: "" }));
    } catch (err) {
      setParseErrors((e) => ({
        ...e,
        [name]: err instanceof Error ? err.message : "invalid JSON",
      }));
    }
  }

  function renderField(name: string, rawSpec: unknown) {
    const spec = specOf(rawSpec);
    const current = draft[name];
    const t = inferType(spec, current);
    const id = `field-${stepIndex}-${name}`;
    const label = (
      <label htmlFor={id} className="block text-xs font-medium text-zinc-700 dark:text-zinc-300">
        {name}
        {spec.required && <span className="text-red-600 ml-0.5">*</span>}
        {spec.description && (
          <span className="ml-2 text-[10px] font-normal text-zinc-500">
            {spec.description}
          </span>
        )}
      </label>
    );
    const common =
      "w-full rounded-md border border-black/10 dark:border-white/15 bg-transparent px-2 py-1.5 text-xs outline-none focus:border-black/40 dark:focus:border-white/40 disabled:opacity-60";

    if (Array.isArray(spec.enum) && spec.enum.length > 0) {
      return (
        <div key={name} className="space-y-1">
          {label}
          <select
            id={id}
            className={common}
            disabled={!editable}
            value={String(current ?? "")}
            onChange={(e) => setField(name, e.target.value)}
          >
            <option value="">—</option>
            {spec.enum.map((opt) => (
              <option key={String(opt)} value={String(opt)}>
                {String(opt)}
              </option>
            ))}
          </select>
        </div>
      );
    }

    if (t === "boolean") {
      return (
        <div key={name} className="flex items-center gap-2">
          <input
            id={id}
            type="checkbox"
            disabled={!editable}
            checked={Boolean(current)}
            onChange={(e) => setField(name, e.target.checked)}
          />
          {label}
        </div>
      );
    }

    if (t === "number" || t === "integer") {
      return (
        <div key={name} className="space-y-1">
          {label}
          <input
            id={id}
            type="number"
            className={common}
            disabled={!editable}
            value={current === undefined || current === null ? "" : Number(current)}
            onChange={(e) =>
              setField(name, e.target.value === "" ? null : Number(e.target.value))
            }
          />
        </div>
      );
    }

    if (t === "array" || t === "object") {
      const text =
        jsonText[name] ?? (current === undefined ? "" : JSON.stringify(current, null, 2));
      return (
        <div key={name} className="space-y-1">
          {label}
          <textarea
            id={id}
            className={`${common} font-mono`}
            rows={Math.min(8, Math.max(2, text.split("\n").length))}
            disabled={!editable}
            value={text}
            onChange={(e) =>
              setJsonField(name, e.target.value, t === "array" ? "array" : "object")
            }
            placeholder={t === "array" ? "[ ... ]" : "{ ... }"}
          />
          {parseErrors[name] && (
            <p className="text-[10px] text-red-600 dark:text-red-400">
              {parseErrors[name]}
            </p>
          )}
        </div>
      );
    }

    return (
      <div key={name} className="space-y-1">
        {label}
        <input
          id={id}
          type="text"
          className={common}
          disabled={!editable}
          value={current === undefined || current === null ? "" : String(current)}
          onChange={(e) => setField(name, e.target.value)}
        />
      </div>
    );
  }

  const schemaKeys = Object.keys(paramSchema);
  const draftKeysNotInSchema = Object.keys(draft).filter((k) => !schemaKeys.includes(k));

  return (
    <div className="flex flex-col h-full">
      <header className="px-4 py-3 border-b border-black/10 dark:border-white/10 flex items-baseline justify-between">
        <div>
          <h2 className="text-sm font-semibold">Step {stepIndex + 1}</h2>
          <p className="text-xs text-zinc-500">
            {block?.name ?? step.block_id} · {step.block_id}
          </p>
        </div>
        <button
          type="button"
          className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 text-lg leading-none"
          onClick={onClose}
          aria-label="Close inspector"
        >
          ×
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {block?.description && (
          <p className="text-xs text-zinc-600 dark:text-zinc-400">{block.description}</p>
        )}

        {Object.keys(step.input_bindings).length > 0 && (
          <section className="space-y-1">
            <h3 className="text-xs font-medium text-zinc-700 dark:text-zinc-300 uppercase tracking-wide">
              Input bindings
            </h3>
            <ul className="text-xs space-y-0.5">
              {Object.entries(step.input_bindings).map(([k, v]) => (
                <li key={k} className="text-zinc-600 dark:text-zinc-400">
                  <span className="font-mono">{k}</span> ← <span className="font-mono">{v}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="space-y-3">
          <h3 className="text-xs font-medium text-zinc-700 dark:text-zinc-300 uppercase tracking-wide">
            Parameters
          </h3>
          {schemaKeys.length === 0 && draftKeysNotInSchema.length === 0 ? (
            <p className="text-xs text-zinc-500 italic">No parameters for this block.</p>
          ) : (
            <>
              {schemaKeys.map((name) => renderField(name, paramSchema[name]))}
              {draftKeysNotInSchema.length > 0 && (
                <div className="space-y-3 pt-2 border-t border-dashed border-black/10 dark:border-white/10">
                  <p className="text-[10px] uppercase tracking-wide text-zinc-500">
                    extra params (not in schema)
                  </p>
                  {draftKeysNotInSchema.map((name) => renderField(name, undefined))}
                </div>
              )}
            </>
          )}
        </section>
      </div>

      {editable && (
        <footer className="border-t border-black/10 dark:border-white/10 p-3 flex items-center justify-between">
          <span className="text-xs text-zinc-500">
            {dirty ? "Unsaved changes" : "Up to date"}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              className="text-xs rounded-md border border-black/10 dark:border-white/15 px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5"
              onClick={() => {
                setDraft({ ...step.params });
                setJsonText({});
                setParseErrors({});
              }}
              disabled={!dirty}
            >
              Reset
            </button>
            <button
              type="button"
              className="text-xs rounded-md bg-zinc-900 px-3 py-1.5 font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
              onClick={() => onSave(draft)}
              disabled={!dirty || Object.values(parseErrors).some(Boolean)}
            >
              Save
            </button>
          </div>
        </footer>
      )}
    </div>
  );
}
