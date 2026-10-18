import { FileTextIcon, PlayIcon, SquareIcon, Trash2Icon } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { useSession } from "../auth";
import { clock } from "../hooks";
import { Md } from "./Md";
import { ErrorLine, ResultLine } from "./kit";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog as DialogRoot,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

/** A modal with a title that pairs sans and serif, as in Design.pen ("Flood *drill*"). */
export function Dialog({
  title,
  serif,
  description,
  onClose,
  children,
  footer,
  wide = false,
}: {
  title: string;
  serif?: string;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  return (
    <DialogRoot open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={cn("max-h-[calc(100dvh-2rem)] gap-5 overflow-y-auto p-6", wide ? "sm:max-w-3xl" : "sm:max-w-lg")}>
        <DialogHeader className="pr-8">
          <DialogTitle className="text-[22px] font-normal tracking-tight">
            {title}
            {serif && <span className="accent-serif"> {serif}</span>}
          </DialogTitle>
          {description && <DialogDescription className="leading-relaxed">{description}</DialogDescription>}
        </DialogHeader>
        {children}
        {footer && <DialogFooter className="-mx-6 -mb-6 px-6">{footer}</DialogFooter>}
      </DialogContent>
    </DialogRoot>
  );
}

interface SimStatus {
  running: boolean;
  sent: number;
  rate_per_min?: number;
  log?: string[];
}

export function DrillDialog({ isAdmin, onClose }: { isAdmin: boolean; onClose: () => void }) {
  const { config } = useSession();
  const [status, setStatus] = useState<SimStatus | null>(null);
  const [rate, setRate] = useState(20);
  const [autoField, setAutoField] = useState(true);
  const [scenario, setScenario] = useState<"demo" | "flood">("demo");
  const [burst, setBurst] = useState(300);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => api.get<SimStatus>("/api/sim/status").then(setStatus);
  useEffect(() => {
    void refresh();
    const t = window.setInterval(refresh, 2000);
    return () => window.clearInterval(t);
  }, []);

  const run = async (fn: () => Promise<unknown>, done?: (r: unknown) => string) => {
    setBusy(true);
    setResult(null);
    try {
      const r = await fn();
      if (done) setResult(done(r));
      await refresh();
    } catch (e) {
      setResult(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title="Flood"
      serif="drill"
      onClose={onClose}
      description={
        <>
          The drill sends realistic, messy help messages to this organisation, including the same household writing twice.
          Simulated field teams deliver when they arrive, and two teams report {config?.area.flood_road} flooded about a
          minute in.
        </>
      }
      footer={
        <>
          {isAdmin && (
            <Button
              variant="ghost"
              className="mr-auto text-destructive"
              disabled={busy}
              onClick={() => run(() => api.post("/api/sim/reset"), () => "This organisation's memory is empty again.")}
            >
              <Trash2Icon data-icon="inline-start" />
              Erase this organisation's memory
            </Button>
          )}
          {status?.running ? (
            <Button variant="destructive" disabled={busy} onClick={() => run(() => api.post("/api/sim/stop"))}>
              <SquareIcon data-icon="inline-start" />
              Stop the drill
            </Button>
          ) : (
            <Button
              disabled={busy}
              onClick={() => run(() => api.post("/api/sim/start", { rate_per_min: rate, auto_field: autoField, scenario }))}
            >
              <PlayIcon data-icon="inline-start" />
              Start the drill
            </Button>
          )}
        </>
      }
    >
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="scenario">Scenario</FieldLabel>
          <NativeSelect id="scenario" value={scenario} onChange={(e) => setScenario(e.target.value as "demo" | "flood")}>
            <NativeSelectOption value="demo">Demo script: Kumar duplicate, unserved street, Das family, road flood</NativeSelectOption>
            <NativeSelectOption value="flood">Random flood: messages only</NativeSelectOption>
          </NativeSelect>
        </Field>
        <Field>
          <div className="flex items-center justify-between">
            <FieldLabel htmlFor="rate">Messages per minute</FieldLabel>
            <span className="num text-sm">{rate}</span>
          </div>
          <Slider
            id="rate"
            min={5}
            max={240}
            step={5}
            value={[rate]}
            onValueChange={(v) => setRate(Array.isArray(v) ? v[0] : (v as number))}
            aria-label="Messages per minute"
          />
        </Field>
        <Field orientation="horizontal">
          <Checkbox id="auto-field" checked={autoField} onCheckedChange={(c) => setAutoField(c === true)} />
          <FieldLabel htmlFor="auto-field" className="font-normal">
            Simulate field teams delivering help
          </FieldLabel>
        </Field>
      </FieldGroup>

      <div className="flex flex-col gap-1.5 rounded-xl bg-muted p-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <span className={cn("size-1.5 rounded-full", status?.running ? "bg-success" : "bg-muted-foreground")} aria-hidden="true" />
          {status ? `${status.running ? "Running" : "Stopped"} · ${status.sent} messages sent` : "Checking…"}
        </div>
        {status?.log?.slice(-4).map((l, i) => (
          <p key={i} className="num text-[10.5px] text-muted-foreground">
            {l}
          </p>
        ))}
      </div>

      <Separator />
      <div className="flex flex-col gap-2">
        <h3 className="font-medium">Load test</h3>
        <p className="text-sm text-muted-foreground">
          Send many messages at once and watch the agents drain the queue without handling any request twice.
        </p>
        <div className="flex items-center gap-2">
          <Input
            className="num w-28"
            type="number"
            min={10}
            max={5000}
            value={burst}
            onChange={(e) => setBurst(+e.target.value)}
            aria-label="Number of messages"
          />
          <Button
            variant="outline"
            disabled={busy}
            onClick={() =>
              run(
                () => api.post<{ count: number; ms: number; per_min: number }>("/api/sim/burst", { count: burst }),
                (r) => {
                  const x = r as { count: number; ms: number; per_min: number };
                  return `Accepted ${x.count} messages in ${x.ms} ms (${x.per_min.toLocaleString()} per minute).`;
                },
              )
            }
          >
            Send {burst} messages
          </Button>
          {isAdmin && (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() =>
                run(() => api.post<{ reopened: string[] }>("/api/sim/reset-roads"), (r) => {
                  const x = r as { reopened: string[] };
                  return x.reopened.length ? `Reopened ${x.reopened.join(", ")}.` : "All roads were already open.";
                })
              }
            >
              Reopen all roads
            </Button>
          )}
        </div>
      </div>
      {result && <ResultLine>{result}</ResultLine>}
    </Dialog>
  );
}

interface Briefing {
  id: string;
  at: number;
  shift: string;
  text: string;
  by: string;
}

export function BriefingDialog({ onClose }: { onClose: () => void }) {
  const [list, setList] = useState<Briefing[] | null>(null);
  const [current, setCurrent] = useState<Briefing | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Briefing[]>("/api/ops/briefings").then((l) => {
      setList(l);
      setCurrent(l[0] ?? null);
    });
  }, []);

  const write = async () => {
    setBusy(true);
    setError(null);
    try {
      const b = await api.post<Briefing>("/api/ops/briefing");
      setCurrent(b);
      setList((l) => [b, ...(l ?? [])]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title="Shift"
      serif="handover"
      onClose={onClose}
      wide
      description="The Shift Coordinator assembles a briefing from the graph. It also writes one at each shift change."
      footer={
        <>
          {list && list.length > 1 && (
            <NativeSelect
              className="mr-auto w-auto"
              aria-label="Earlier briefings"
              value={current?.id}
              onChange={(e) => setCurrent(list.find((b) => b.id === e.target.value) ?? null)}
            >
              {list.map((b) => (
                <NativeSelectOption key={b.id} value={b.id}>
                  {b.shift}, {clock(b.at)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          )}
          <Button disabled={busy} onClick={write}>
            <FileTextIcon data-icon="inline-start" />
            {busy ? "Writing the briefing…" : "Write a briefing now"}
          </Button>
        </>
      }
    >
      {error && <ErrorLine>{error}</ErrorLine>}
      {current ? (
        <div className="flex flex-col gap-3">
          <div className="rounded-xl border bg-card p-5 text-sm leading-relaxed [&_h2]:mt-3 [&_h2]:text-lg [&_h2]:font-medium [&_h2]:first:mt-0 [&_h3]:mt-3 [&_h3]:font-medium [&_li]:ml-5 [&_li]:list-disc [&_p]:mt-2 [&_ul]:mt-2">
            <Md text={current.text} />
          </div>
          <span className="eyebrow">
            [ {current.by === "rules" ? "Assembled from the graph" : `Written by ${current.by}`} at {clock(current.at)} ]
          </span>
        </div>
      ) : (
        list && <ResultLine>No briefing yet for this organisation.</ResultLine>
      )}
    </Dialog>
  );
}

export function MessageDialog({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  const [channel, setChannel] = useState("phone");
  const [sent, setSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      title="Add a helpline"
      serif="message"
      onClose={onClose}
      description="Paste or type a message exactly as it came in. The Intake agent reads Hinglish and typos."
      footer={
        <Button
          disabled={busy || text.trim().length < 3}
          onClick={async () => {
            setBusy(true);
            try {
              const r = await api.post<{ id: string }>("/api/ops/messages", { text, channel });
              setSent(r.id);
              setText("");
            } finally {
              setBusy(false);
            }
          }}
        >
          Add message
        </Button>
      }
    >
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="msg">Message</FieldLabel>
          <Textarea
            id="msg"
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Das family ward 14 near water tanki, 6 log, nani bimar hai"
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="ch">Came in by</FieldLabel>
          <NativeSelect id="ch" value={channel} onChange={(e) => setChannel(e.target.value)}>
            <NativeSelectOption value="phone">Phone call</NativeSelectOption>
            <NativeSelectOption value="whatsapp">WhatsApp</NativeSelectOption>
            <NativeSelectOption value="social">Social media</NativeSelectOption>
            <NativeSelectOption value="sms">SMS</NativeSelectOption>
          </NativeSelect>
          {sent && <FieldDescription>Added as {sent}. Watch it move through the pipeline.</FieldDescription>}
        </Field>
      </FieldGroup>
    </Dialog>
  );
}
