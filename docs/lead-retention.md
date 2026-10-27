# Lead retention and deletion (P1)

How GWA deletes contact messages (leads), on request or when a business's
retention period runs out — and, just as important, what it does **not**
delete. Code: `apps/api/app/leads/retention.py`. Migration:
`c4d9e2a7f1b3_p1_lead_deletion_events` (additive: one table).

## What GWA deletes

| Record | Holds | On deletion |
|---|---|---|
| `leads` row | name, email, phone, message, form details, page URL | deleted |
| `lead_notes` | operator notes about the lead | deleted |
| `internal_notifications` linked to the lead | a summary naming the visitor | deleted |
| `lead_deletion_events` | who/what deleted it, when, why, counts | **written** (no visitor data) |

Scope is always tenant + business + lead: a lead of another business or
tenant is "not found" and never touched. Deleting an already-deleted lead
is a no-op (204), so a retry is always safe.

Known gap: an internal notification created by an n8n callback that did not
carry the lead id has no link to the lead, so it cannot be found and
deleted with it. Current n8n workflows send the id.

## Deleting one lead (e.g. an erasure request)

`DELETE /businesses/{business_id}/leads/{lead_id}` — a signed-in operator
with access to the tenant (session cookie + CSRF token; the legacy header
auth is not accepted). There is no Studio button yet; until there is, the
operator calls the API from a signed-in session.

## Retention period

Per business, in the business config: `lead_management.retention_days`
(1–3650; unset = never deleted automatically). A lead expires when its last
activity in GWA — the later of its last update (e.g. a status change) and
its newest note — is older than that many days. Mark a lead "contacted"
when you reply, so the period counts from the last exchange.

The period visitors read is the owner's own wording in
`legal_profile.data_retention`; keep both consistent (GWA does not derive
one from the other). Example: wording "como máximo, 12 meses desde nuestra
última comunicación" ↔ `retention_days: 365`.

## Running the retention job

```sh
cd apps/api
python -m app.leads.retention                        # dry run: lists what would be deleted
python -m app.leads.retention --business-id <uuid>   # dry run, one business
python -m app.leads.retention --apply                # deletes what the dry run lists
```

Output is JSON with counts and dates per business — never visitor data.
Always run the dry run first and compare. The job uses the configured
database; running it against production is a production write and needs
explicit approval each time. No scheduler is set up: run it monthly (or
add a scheduled job later — not configured today).

## What GWA does NOT delete (verify each with its provider)

| Copy | Where | What to do |
|---|---|---|
| n8n execution history | the n8n instance (Railway) | n8n stores each execution's payload, including the full lead. Check the instance's execution pruning settings and keep the maximum age shorter than the retention period. Not verified from GWA. |
| Resend logs | Resend | The owner notification and the visitor's acknowledgement pass through Resend; their logs keep message data for the plan's retention window. Check the account's plan. Not verified from GWA. |
| Database backups | Railway Postgres | A deleted lead remains in backups until they rotate out. Check the backup window. Not verified from GWA. |
| Owner's inbox | the owner's email provider | The owner notification contains the visitor's name, email and message. The owner deletes them (and the replies) when the period ends. |
| Visitor's inbox | the visitor's email provider | The acknowledgement email; outside the business's control. |

GWA can only claim deletion from its own database. A privacy notice should
say messages are deleted "de nuestros sistemas" only once each external copy
above has its own verified limit.
