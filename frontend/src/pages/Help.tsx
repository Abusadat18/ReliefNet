import { CheckIcon, MessageSquarePlusIcon, PhoneCallIcon, SendIcon } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { BrandMark, ErrorLine, Eyebrow } from "../components/kit";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";

const NEXT_STEPS = [
  "Our agents read your message and check for earlier ones from your household.",
  "A coordinator gives it a priority. Medical needs go first.",
  "The nearest free team gets your location and a safe route.",
];

/** Public help form. No sign-in: people in distress should not need an account. */
export function Help() {
  const params = useParams();
  const [orgs, setOrgs] = useState<{ slug: string; name: string }[]>([]);
  const [org, setOrg] = useState(params.org ?? "");
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ref, setRef] = useState<string | null>(null);
  const [example, setExample] = useState("");

  useEffect(() => {
    api
      .get<{ area?: { example_help: string } }>("/api/config")
      .then((c) => setExample(c.area?.example_help ?? ""))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    api.get<{ slug: string; name: string }[]>("/api/public/orgs").then((o) => {
      setOrgs(o);
      if (!params.org && o[0]) setOrg(o[0].slug);
    });
  }, [params.org]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ reference: string }>(`/api/public/${org}/help`, { text, name, phone });
      setRef(r.reference);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="min-h-dvh bg-background">
      <div className="mx-auto flex min-h-dvh max-w-lg flex-col">
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <Link to="/" className="flex items-center gap-2">
            <BrandMark className="size-5" />
            <span className="font-display text-[15px] font-semibold tracking-tight">ReliefNet</span>
          </Link>
          <span className="num text-[11px] text-muted-foreground" lang="hi">
            हिंदी · EN
          </span>
        </div>

        {ref ? (
          <div className="flex flex-1 flex-col gap-6 px-5 py-6" aria-live="polite">
            <span className="grid size-12 place-items-center rounded-full bg-success-soft text-success">
              <CheckIcon className="size-6" aria-hidden="true" />
            </span>
            <div className="flex flex-col gap-2">
              <h1 className="text-[32px] leading-tight font-normal tracking-tight">
                Request <span className="accent-serif">received</span>
              </h1>
              <p className="text-[15px] leading-relaxed text-muted-foreground" lang="hi">
                आपका संदेश मिल गया। Stay where you are if it is safe.
              </p>
            </div>
            <div className="flex flex-col gap-1 rounded-2xl bg-slate p-5 text-white">
              <span className="eyebrow text-[#9fb0b6]">[ Your reference ]</span>
              <span className="num text-[44px] leading-tight font-semibold tracking-tight">{ref}</span>
              <span className="text-[13px] text-[#c9d3d6]">Say this number if you call or message again.</span>
            </div>
            <div className="flex flex-col">
              <Eyebrow>What happens next</Eyebrow>
              <ol className="mt-1">
                {NEXT_STEPS.map((t, i) => (
                  <li key={t} className="flex gap-3 border-b py-3 last:border-b-0">
                    <span className="num text-[13px] text-muted-foreground">[0{i + 1}]</span>
                    <span className="text-sm leading-relaxed">{t}</span>
                  </li>
                ))}
              </ol>
            </div>
            <p className="text-sm text-muted-foreground">
              If anything changes, such as water rising or someone falling ill, send a new message and mention this number.
            </p>
            <Button
              variant="outline"
              size="lg"
              className="mt-auto w-full"
              onClick={() => {
                setRef(null);
                setText("");
              }}
            >
              <MessageSquarePlusIcon data-icon="inline-start" />
              Send another message
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} className="flex flex-1 flex-col">
            <div className="px-4">
              <p className="flex items-center gap-2.5 rounded-full bg-destructive px-4 py-2.5 text-[13px] font-semibold text-white" role="note">
                <PhoneCallIcon className="size-4 shrink-0" aria-hidden="true" />
                Someone drowning or badly hurt? Call 112 now.
              </p>
            </div>
            <div className="flex flex-1 flex-col gap-5 px-5 py-6">
              <div className="flex flex-col gap-1.5">
                <h1 className="text-[32px] leading-tight font-normal tracking-tight">
                  Ask for flood <span className="accent-serif">help</span>
                </h1>
                <p className="text-[15px] leading-relaxed text-muted-foreground" lang="hi">
                  बाढ़ में मदद चाहिए? Write in Hindi, Hinglish or English.
                </p>
              </div>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="what">What is happening?</FieldLabel>
                  <Textarea
                    id="what"
                    rows={5}
                    required
                    minLength={5}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder={example ? `e.g. ${example}` : ""}
                    className="min-h-32 rounded-xl text-[15px]"
                  />
                  <FieldDescription>Say how many people, what you need, and a landmark or ward.</FieldDescription>
                </Field>
                <ul className="flex flex-col gap-1.5 text-[13px] text-muted-foreground">
                  <li>· How many people, and if there are children, elderly, sick or pregnant people</li>
                  <li>· What you need: boat, medicine, food, drinking water</li>
                  <li>· The nearest landmark and ward number</li>
                </ul>
                <div className="grid grid-cols-2 gap-3">
                  <Field>
                    <FieldLabel htmlFor="nm">Name (optional)</FieldLabel>
                    <Input id="nm" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="ph">Phone (optional)</FieldLabel>
                    <Input id="ph" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="tel" />
                  </Field>
                </div>
                <FieldDescription>
                  We use your own phone number to find your household, so a second message does not send a second team.
                </FieldDescription>
                {orgs.length > 1 && !params.org && (
                  <Field>
                    <FieldLabel htmlFor="org">Relief organisation</FieldLabel>
                    <NativeSelect id="org" value={org} onChange={(e) => setOrg(e.target.value)}>
                      {orgs.map((o) => (
                        <NativeSelectOption key={o.slug} value={o.slug}>
                          {o.name}
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                  </Field>
                )}
              </FieldGroup>
              {error && <ErrorLine>{error}</ErrorLine>}
            </div>
            <div className="sticky bottom-0 flex flex-col gap-2 border-t bg-background px-5 pt-3 pb-[max(20px,env(safe-area-inset-bottom))]">
              <Button type="submit" size="lg" className="h-12 w-full text-base" disabled={busy || text.trim().length < 5 || !org}>
                <SendIcon data-icon="inline-start" />
                {busy ? "Sending…" : "Send help request"}
              </Button>
              <p className="text-center text-xs text-muted-foreground">No sign-in needed. Our agents read your message as soon as it arrives.</p>
            </div>
          </form>
        )}
      </div>
    </main>
  );
}
