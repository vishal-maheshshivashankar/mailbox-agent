"""Email classification via Gemini 2.5 Flash Lite.

Chosen for cost: classification is a high-volume, low-complexity task (short
inputs, small fixed label set), which is exactly what a "lite" tier model is
priced for. Only sender/subject/snippet are sent, never full bodies - keeps
each call small and cheap. See docs/ARCHITECTURE.md section 5.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from mailbox_agent import config
from mailbox_agent.toolkit.models import BatchClassification, Classification, EmailSummary

SYSTEM_PROMPT = """You triage email for a personal Gmail inbox. For each message, pick exactly one category:

- important: needs the person's attention or action soon. Routine automated
  financial notifications belong in statements/e_mandate/receipts below, not
  here - reserve "important" for things like security alerts, fraud
  warnings, deadlines, or a genuine unexpected problem.
- personal: real correspondence from a known individual, not automated
- receipts: one-off order/purchase confirmations for a single ad-hoc
  transaction - e-commerce orders, individual purchases, one-time payments.
  Judge by what the payment is FOR, not the literal wording of the email: a
  recurring/pre-authorized payment (an insurance premium, an EMI, a
  subscription) belongs in e_mandate below even if the email itself is
  titled "receipt" or "payment receipt."
- statements: periodic bank or credit card account statements/summaries
  (monthly statement, e-statement, billing-cycle summary) - not a single
  transaction receipt
- e_mandate: recurring or pre-authorized payment activity - EMI payments,
  insurance premium payments (including ones titled "premium receipt" or
  "payment receipt" - an insurance premium is inherently recurring),
  subscription auto-renewals, standing instruction / NACH / ECS mandate
  registration or debit notices
- newsletters: opt-in content digests, blog/newsletter subscriptions
- social: notifications from social networks, forums, community platforms
- promotions: marketing, sales, discounts, advertising
- other: anything that doesn't clearly fit above

For financial/bank senders, check statements and e_mandate BEFORE important
or receipts - a routine monthly statement or a routine recurring payment
confirmation is not "important" just because it's from a bank, and not
"receipts" just because the email uses that word.

Judge only from sender, subject, and snippet. Prefer "promotions" or
"newsletters" over "important" when in doubt - the user wants aggressive
sorting of low-value mail, not an inbox where everything is "important".
Return a confidence between 0 and 1 for each."""


def _client() -> ChatGoogleGenerativeAI:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return ChatGoogleGenerativeAI(
        model=config.GEMINI_MODEL,
        google_api_key=config.GEMINI_API_KEY,
        temperature=0,
    )


def _format_email(msg: EmailSummary) -> str:
    return f"id={msg.id}\nfrom={msg.sender}\nsubject={msg.subject}\nsnippet={msg.snippet[:300]}"


def classify_batch(messages: list[EmailSummary], batch_size: int = 20) -> list[Classification]:
    if not messages:
        return []

    llm = _client().with_structured_output(BatchClassification)
    results: list[Classification] = []

    for i in range(0, len(messages), batch_size):
        chunk = messages[i : i + batch_size]
        body = "\n\n---\n\n".join(_format_email(m) for m in chunk)
        response = llm.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=f"Classify these {len(chunk)} emails:\n\n{body}"),
            ]
        )
        if not isinstance(response, BatchClassification):
            # with_structured_output's return type is technically dict | BaseModel;
            # this narrows it and doubles as a runtime guard against a malformed response.
            raise TypeError(f"expected BatchClassification from Gemini, got {type(response)}")
        by_id = {c.message_id: c for c in response.results}
        for msg in chunk:
            if msg.id in by_id:
                results.append(by_id[msg.id])
            else:
                # Model skipped one - fail safe, don't silently drop it from review.
                results.append(
                    Classification(message_id=msg.id, category="other", confidence=0.0, reason="unclassified")
                )

    return results
