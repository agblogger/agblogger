import { useState } from "react";
import { Link } from "react-router-dom";
import AlertBanner from "@/components/AlertBanner";
import { subscribe } from "@/api/subscriptions";
import { HTTPError } from "@/api/client";
import { useSiteStore } from "@/stores/siteStore";

export default function SubscribePage() {
  const compliance = useSiteStore(
    (state) => state.config?.subscription_compliance,
  );
  const privacyPolicyUrl = compliance?.privacy_policy_url ?? "";
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await subscribe(email);
      setDone(true);
    } catch (err) {
      setError(
        err instanceof HTTPError && err.response.status === 429
          ? "Too many requests. Please try again later."
          : "Subscriptions are currently unavailable. Please try again later.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <div className="max-w-sm mx-auto pt-16 text-center animate-fade-in">
        <h1 className="font-display text-3xl text-ink mb-4">Almost there</h1>
        <p className="text-muted leading-relaxed">
          Please check your inbox to confirm your subscription.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-sm mx-auto pt-16 animate-fade-in">
      <h1 className="font-display text-3xl text-center mb-8">Subscribe</h1>

      <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
        {error !== null && <AlertBanner variant="error">{error}</AlertBanner>}

        <div>
          <label
            htmlFor="sub-email"
            className="block text-sm font-medium text-ink mb-1.5"
          >
            Email
          </label>
          <input
            id="sub-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setError(null);
            }}
            disabled={submitting}
            placeholder="you@example.com"
            className="w-full px-4 py-2.5 bg-paper-warm border border-border rounded-lg
                     text-ink focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20
                     transition-colors disabled:opacity-50"
          />
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-2.5 bg-accent text-white rounded-lg font-medium
                   hover:bg-accent-light disabled:opacity-50 transition-colors"
        >
          {submitting ? "Subscribing…" : "Subscribe"}
        </button>
      </form>

      <p className="text-xs text-muted mt-6 leading-relaxed">
        We use your email only to notify you of new posts. Your data is
        processed by{" "}
        <a
          href="https://resend.com"
          className="underline hover:text-ink transition-colors"
        >
          Resend
        </a>
        . See our{" "}
        {privacyPolicyUrl !== "" ? (
          <a
            href={privacyPolicyUrl}
            className="underline hover:text-ink transition-colors"
          >
            Privacy Policy
          </a>
        ) : (
          <Link
            to="/page/privacy"
            className="underline hover:text-ink transition-colors"
          >
            Privacy Policy
          </Link>
        )}
        .
      </p>
    </div>
  );
}
