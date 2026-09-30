import { useState } from "react";

import { sendEnquiry, type EnquiryInput } from "../../server/enquiry.functions";

export function Contact() {
  const [state, setState] = useState<"idle" | "sending" | "done" | "failed">("idle");

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget)) as EnquiryInput;
    if (!values.fullName || !values.contactEmail) {
      setState("failed");
      return;
    }
    setState("sending");
    try {
      await sendEnquiry({ data: values });
      setState("done");
    } catch {
      setState("failed");
    }
  }

  if (state === "done") {
    return (
      <section className="contact" id="contact">
        <p className="contact__done">Thanks. We will call you to book the assessment.</p>
      </section>
    );
  }

  return (
    <section className="contact" id="contact">
      <h2 className="section-title">Book an assessment</h2>
      <form className="contact__form" onSubmit={onSubmit}>
        <label htmlFor="c-name">Your name</label>
        <input id="c-name" name="fullName" required type="text" />

        <label htmlFor="c-treatment">Treatment</label>
        <select id="c-treatment" name="treatment">
          <option value="sports-physiotherapy">Sports physiotherapy</option>
          <option value="clinical-pilates">Clinical pilates</option>
          <option value="osteopathy">Osteopathy</option>
          <option value="other">Not sure yet</option>
        </select>

        <label htmlFor="c-email">Email</label>
        <input id="c-email" name="contactEmail" required type="email" />

        <label htmlFor="c-phone">Phone (optional)</label>
        <input id="c-phone" name="telephone" type="tel" />

        <label htmlFor="c-time">Preferred time</label>
        <select id="c-time" name="preferredTime">
          <option value="morning">Morning</option>
          <option value="afternoon">Afternoon</option>
        </select>

        <label htmlFor="c-message">What is going on?</label>
        <textarea id="c-message" name="message" rows={4} />

        <label className="contact__consent" htmlFor="c-privacy">
          <input id="c-privacy" name="acceptPrivacy" required type="checkbox" value="yes" /> I accept the privacy
          policy
        </label>

        <button className="contact__submit" disabled={state === "sending"} type="submit">
          {state === "sending" ? "Sending" : "Request a call"}
        </button>
        {state === "failed" ? <p className="contact__error">Something went wrong. Please try again.</p> : null}
      </form>
    </section>
  );
}
