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
| `Process`      | Ordered sequence of steps ("how it works"), rendered as a native `<ol>`. |
| `Gallery`      | Grid of items (projects, work samples), each with an image and optional before/after pair. |
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
| `items`     | `ServiceItem[]`    | `{ title, description, icon?, image?: BlockImage, action?: BlockAction }` — `image` takes precedence over `icon` when both are set. |

### Features — `FeaturesContent`

| Field       | Type              | Notes                          |
| ----------- | ------------------ | --------------------------------- |
| `heading`   | `string?`          |                                    |
| `subheading`| `string?`          |                                    |
| `items`     | `FeatureItem[]`    | `{ title, description, icon? }` — no per-item action, unlike `Services`. |

### Process — `ProcessContent`

| Field       | Type              | Notes                          |
| ----------- | ------------------ | --------------------------------- |
| `heading`   | `string?`          |                                    |
| `subheading`| `string?`          |                                    |
| `steps`     | `ProcessStep[]`    | `{ title, description, icon? }`, rendered as a native `<ol>` — step numbers come from list position, not content. |

### Gallery — `GalleryContent`

| Field       | Type              | Notes                          |
| ----------- | ------------------ | --------------------------------- |
| `heading`   | `string?`          |                                    |
| `subheading`| `string?`          |                                    |
| `items`     | `GalleryItem[]`    | `{ title, category?, image: BlockImage, description?, link?: BlockAction, beforeAfter?: { before: BlockImage, after: BlockImage, beforeLabel?, afterLabel? } }`. When `beforeAfter` is set it's rendered instead of `image`. |

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

`ContactFormField` is a discriminated union on `type`: `text \| email \| tel \| textarea` (default `text`, plain `<input>`/`<textarea>`), `select` and `radio` (require `options: { label, value }[]`), `checkbox` (`options` omitted renders a single toggle, `options` set renders a checkbox group), and `file` (`accept?`, `multiple?` — presentational only, no upload wiring). `radio` and multi-option `checkbox` render inside a `<fieldset>`/`<legend>` rather than a `<label>`, since a label can't correctly describe a group of inputs.

### Shared types

| Type          | Shape                                                    |
| -------------- | ----------------------------------------------------------- |
| `BlockAction`  | `{ label, href, variant?: "solid" \| "outline" \| "ghost" }` — maps directly onto `ui`'s `Button` variant. |
| `BlockImage`   | `{ src, alt, width?, height? }` — `alt` is required.        |

## Type-checking

Blocks are `.astro` files, so `pnpm check` here runs `astro check` (same as
`packages/ui`), not plain `tsc`.

## Deliberately not included

`Navbar`, `Footer`, `Pricing`, booking, chatbot, blog, file upload
infrastructure (the `Contact` block's `file` field type is configuration-only),
and any client-specific block. See the repo root `CLAUDE.md` and
`docs/architecture.md` for current scope.
