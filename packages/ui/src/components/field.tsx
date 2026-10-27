import type { ReactNode } from "react";
import { useId } from "react";
import { cn } from "../cn";
import { fieldError, fieldLabel, hint as hintStyle } from "../styles";
import { Label } from "./label";

export type FieldIds = {
  /** put on the control */
  id: string;
  /** put on the control as `aria-describedby`; names the hint and the error when there is one */
  describedBy: string | undefined;
  /** true when the field has an error */
  invalid: boolean;
};

/**
 * A labelled control: the label above, the control, then one hint line and, when there is one, the error. Given a
 * function as children, it hands over the ids that wire the label, the hint and the error to the control.
 */
export function Field({
  id,
  label,
  hint,
  error,
  optional,
  children,
  className,
}: {
  id?: string;
  label: string;
  hint?: ReactNode;
  error?: string | null;
  /** says "(optional)" after the label */
  optional?: boolean;
  children: ReactNode | ((ids: FieldIds) => ReactNode);
  className?: string;
}) {
  const own = useId();
  const controlId = id ?? own;
  const hintId = `${controlId}-hint`;
  const errorId = `${controlId}-error`;
  const describedBy =
    [hint ? hintId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("grid gap-1.5", className)} data-slot="field">
      <Label htmlFor={controlId} className={fieldLabel}>
        {label}
        {optional ? <span className="font-normal text-muted-foreground"> (optional)</span> : null}
      </Label>
      {typeof children === "function"
        ? children({ id: controlId, describedBy, invalid: Boolean(error) })
        : children}
      {hint ? (
        <span id={hintId} className={hintStyle}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={errorId} className={fieldError} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}
