import { Check, CircleDot, LoaderCircle, XCircle } from "lucide-react";
import { Badge } from "./ui/badge";
import { statusLabel, statusVariant } from "../lib/dashboard";
import type { RunState } from "../types";

export function StatusIcon({ status }: { status: RunState["status"] }) {
  if (["running", "starting", "stopping"].includes(status)) {
    return <LoaderCircle className="h-3.5 w-3.5 animate-spin" />;
  }
  if (status === "completed") return <Check className="h-3.5 w-3.5" />;
  if (status === "failed") return <XCircle className="h-3.5 w-3.5" />;
  return <CircleDot className="h-3.5 w-3.5" />;
}

export function RunStatusBadge({ status }: { status: RunState["status"] }) {
  return (
    <Badge variant={statusVariant(status)} className="gap-1.5">
      <StatusIcon status={status} />
      {statusLabel(status)}
    </Badge>
  );
}
