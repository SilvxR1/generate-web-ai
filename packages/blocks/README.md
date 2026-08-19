# @generate-web-ai/blocks

Reusable, composable page sections built from `@generate-web-ai/ui`
primitives. A client page is assembled as an ordered list of these blocks
plus content, not new code.

Every block takes a single `content` prop — a plain, typed object — plus
optional `id` (for anchor navigation) and `class`. Blocks are business-agnostic:
no client names, branding, colors, fonts, or industry-specific copy live in
this package. They are styled entirely through the same `--ui-*` CSS custom
properties `packages/ui` exposes, so theming a client site themes blocks too.

## Blocks

| Block          | Purpose                                                        |
| -------------- | ---------------------------------------------------------------- |
| `Hero`         | Top-of-page banner: headline, subheading, up to two actions, optional image. |
| `Services`     | Grid of business offerings, each optionally linking to more detail. |
| `Features`     | Informational list of value propositions/benefits (no actions).  |
| `Testimonials` | Customer quotes with attribution, optional rating.                |
| `FAQ`          | Question/answer pairs as native, JS-free `<details>` disclosures. |
| `CTA`          | Focused call-to-action banner with up to two actions.             |
| `Contact`      | Contact details plus an optional, presentational contact form.    |

```astro
---
import { Hero, type HeroContent } from "@generate-web-ai/blocks";

const hero: HeroContent = {
  eyebrow: "Locally owned",
  heading: "Reliable plumbing, day or night",
  subheading: "Licensed, insured, and on call across the metro area.",
  primaryAction: { label: "Book a visit", href: "/contact" },
  secondaryAction: { label: "Our services", href: "#services" },
};
---

<Hero content={hero} />
```

### Hero — `HeroContent`

| Field            | Type          | Notes                                  |
| ----------------- | ------------- | ---------------------------------------- |
| `eyebrow`         | `string?`     | Small label above the heading.           |
| `heading`         | `string`      | Rendered as the page's `<h1>`.           |
| `subheading`      | `string?`     |                                           |
| `primaryAction`   | `BlockAction?`|                                           |
| `secondaryAction` | `BlockAction?`|                                           |
| `image`           | `BlockImage?` | Rendered beside the copy on wide screens.|

### Services — `ServicesContent`

| Field       | Type              | Notes                          |
| ----------- | ------------------ | --------------------------------- |
| `heading`   | `string?`          |                                    |
| `subheading`| `string?`          |                                    |
| `items`     | `ServiceItem[]`    | `{ title, description, icon?, action?: BlockAction }` |

### Features — `FeaturesContent`

| Field       | Type              | Notes                          |
| ----------- | ------------------ | --------------------------------- |
| `heading`   | `string?`          |                                    |
| `subheading`| `string?`          |                                    |
| `items`     | `FeatureItem[]`    | `{ title, description, icon? }` — no per-item action, unlike `Services`. |

### Testimonials — `TestimonialsContent`

| Field       | Type                | Notes                          |
| ----------- | -------------------- | --------------------------------- |
| `heading`   | `string?`            |                                    |
| `subheading`| `string?`            |                                    |
| `items`     | `TestimonialItem[]`  | `{ quote, author, role?, company?, avatar?: BlockImage, rating?: number }` |

### FAQ — `FAQContent`

| Field       | Type       | Notes                          |
| ----------- | ----------- | --------------------------------- |
| `heading`   | `string?`   |                                    |
| `subheading`| `string?`   |                                    |
| `items`     | `FAQItem[]` | `{ question, answer }`            |

### CTA — `CTAContent`

| Field             | Type           | Notes |
| ------------------ | -------------- | ----- |
| `heading`           | `string`       |       |
| `subheading`        | `string?`      |       |
| `primaryAction`     | `BlockAction`  |       |
| `secondaryAction`   | `BlockAction?` |       |

### Contact — `ContactContent`

| Field       | Type              | Notes                                  |
| ----------- | ------------------ | ------------------------------------------ |
| `heading`   | `string?`          |                                             |
| `subheading`| `string?`          |                                             |
| `details`   | `ContactDetail[]?` | `{ label, value, href? }` — phone, email, address, hours, etc. |
| `form`      | `ContactForm?`     | `{ action?, method?, fields: ContactFormField[], submitLabel? }`. Renders a native `<form>`; submission wiring is a site/app concern, not this block's. |

### Shared types

| Type          | Shape                                                    |
| -------------- | ----------------------------------------------------------- |
| `BlockAction`  | `{ label, href, variant?: "solid" \| "outline" \| "ghost" }` — maps directly onto `ui`'s `Button` variant. |
| `BlockImage`   | `{ src, alt, width?, height? }` — `alt` is required.        |

## Type-checking

Blocks are `.astro` files, so `pnpm check` here runs `astro check` (same as
`packages/ui`), not plain `tsc`.

## Deliberately not included

`Navbar`, `Footer`, `Gallery`, `Pricing`, booking, chatbot, blog, and any
client-specific block. See the repo root `CLAUDE.md` and `docs/architecture.md`
for current scope.
