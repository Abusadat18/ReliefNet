import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";

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
    <main className="help">
      <div className="help-card">
        {ref ? (
          <div className="help-done" aria-live="polite">
            <h1>Request received</h1>
            <p className="hi">Your reference number:</p>
            <span className="ref num">{ref}</span>
            <p>
              Relief teams are being coordinated now. If anything changes, such as water rising or someone falling ill,
              send a new message and mention this number.
            </p>
            <div>
              <button type="button" className="btn" onClick={() => { setRef(null); setText(""); }}>
                Send another message
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} style={{ display: "grid", gap: 18 }}>
            <h1>Ask for flood help</h1>
            <p className="hi" lang="hi">
              बाढ़ में मदद चाहिए? Hindi, Hinglish or English, any language is fine.
            </p>
            <p className="urgent">If someone is drowning or badly hurt, also call 112.</p>
            <div className="field">
              <label htmlFor="what">What is happening?</label>
              <textarea
                id="what"
                className="input"
                rows={5}
                required
                minLength={5}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={example ? `e.g. ${example}` : ""}
              />
            </div>
            <ul>
              <li>How many people, and if there are children, elderly, sick or pregnant people</li>
              <li>What you need: boat, medicine, food, drinking water</li>
              <li>The nearest landmark and ward number</li>
            </ul>
            <div className="field">
              <label htmlFor="nm">Your name or family name (optional)</label>
              <input id="nm" className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="ph">Phone number for a call back (optional)</label>
              <input id="ph" className="input" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
            {orgs.length > 1 && !params.org && (
              <div className="field">
                <label htmlFor="org">Relief organisation</label>
                <select id="org" className="input" value={org} onChange={(e) => setOrg(e.target.value)}>
                  {orgs.map((o) => (
                    <option key={o.slug} value={o.slug}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {error && <p className="error">{error}</p>}
            <div>
              <button type="submit" className="btn primary" disabled={busy || text.trim().length < 5 || !org}>
                {busy ? "Sending…" : "Send help request"}
              </button>
            </div>
          </form>
        )}
      </div>
    </main>
  );
}
