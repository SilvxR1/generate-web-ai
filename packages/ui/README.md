# @generate-web-ai/ui

Reusable, accessible UI primitives — the design-system layer that every
client site's `packages/blocks` are built from.

v0.1: seven primitives, no client site yet. Components are `.astro` files
(zero client-side JS, native semantic HTML), consumed as TypeScript/Astro
source directly — there is no build step for this package.

## Components

| Component   | Renders                          | Purpose                                                        |
| ----------- | --------------------------------- | ---------------------------------------------------------------- |
| `Button`    | `<button>` or `<a>`               | A call-to-action or in-page action.                               |
| `Container` | configurable tag (default `div`)  | Centers content and applies consistent gutters/max-width.        |
| `Card`      | configurable tag (default `div`)  | A surface for grouping related content.                          |
| `Badge`     | `<span>` or `<li>`                | A small status/metadata label.                                   |
| `Heading`   | `<h1>`-`<h6>`                     | A semantic heading with an independently chosen visual size.     |
| `Text`      | `<p>`, `<span>`, or `<div>`       | Body copy.                                                       |
| `Link`      | `<a>`                             | An inline text link, for navigation and in-copy references.      |

```astro
---
import { Badge, Button, Card, Container, Heading, Link, Text } from "@generate-web-ai/ui";
---

<Container size="md">
  <Heading level={1}>Welcome</Heading>
  <Text variant="muted">A short line of supporting copy.</Text>

  <Card variant="elevated" padding="lg">
    <Badge variant="primary">New</Badge>
    <Heading level={2} size="lg">Book a consultation</Heading>
    <Text>Tell us about your project and we'll get back to you.</Text>
    <Button href="/contact">Get started</Button>
  </Card>

  <Text size="sm">
    Read our <Link href="/policy">policy</Link> or visit
    <Link href="https://example.com" external>our partner site</Link>.
  </Text>
</Container>
```

### Button

Primary interactive action element. Renders a native `<button>`, or a native
`<a>` when `href` is passed, so it can act as a styled link without losing
correct semantics or keyboard behavior. `target="_blank"` automatically gets
a safe `rel` if none is given.

| Prop         | Type                                  | Default     |
| ------------ | -------------------------------------- | ----------- |
| `variant`    | `"solid" \| "outline" \| "ghost"`      | `"solid"`   |
| `size`       | `"sm" \| "md" \| "lg"`                 | `"md"`      |
| `href`       | `string`                               | —           |
| `type`       | `"button" \| "submit" \| "reset"`      | `"button"`  |
| `disabled`   | `boolean`                              | `false`     |
| `target`     | `"_blank" \| "_self" \| "_parent" \| "_top"` | —     |
| `rel`        | `string`                               | —           |
| `class`      | `string`                               | —           |

### Container

The layout primitive every page section wraps itself in, for a consistent
content width and side gutters.

| Prop   | Type                                                        | Default |
| ------ | ------------------------------------------------------------ | ------- |
| `as`   | `"div" \| "section" \| "header" \| "footer" \| "main" \| "article"` | `"div"` |
| `size` | `"sm" \| "md" \| "lg" \| "xl" \| "full"`                     | `"lg"`  |
| `class`| `string`                                                      | —       |

### Card

A surface for grouping related content (a service, a pricing tier, a
feature). Composition — headings, text, badges, buttons — is left to the
caller; Card only provides the padding/border/radius/background.

| Prop      | Type                              | Default      |
| --------- | ----------------------------------- | ------------ |
| `as`      | `"div" \| "article" \| "li"`       | `"div"`      |
| `padding` | `"sm" \| "md" \| "lg"`              | `"md"`       |
| `variant` | `"flat" \| "outlined" \| "elevated"`| `"outlined"` |
| `class`   | `string`                            | —            |

### Badge

A small, non-interactive label for status or metadata. For a clickable tag,
wrap a `Badge` in a `Link` or use `Button`.

| Prop      | Type                                                          | Default    |
| --------- | ---------------------------------------------------------------- | ---------- |
| `variant` | `"neutral" \| "primary" \| "success" \| "warning" \| "danger"`  | `"neutral"`|
| `as`      | `"span" \| "li"`                                                 | `"span"`   |
| `class`   | `string`                                                          | —          |

### Heading

A semantic heading (`level` maps directly to `h1`-`h6`) with a visual size
chosen independently, so document outline / SEO stays correct regardless of
how a design wants a given heading to look.

| Prop    | Type                                              | Default                        |
| ------- | ---------------------------------------------------- | ------------------------------- |
| `level` | `1 \| 2 \| 3 \| 4 \| 5 \| 6` (required)              | —                                |
| `size`  | `"sm" \| "md" \| "lg" \| "xl" \| "2xl" \| "3xl"`     | scaled from `level` if omitted  |
| `class` | `string`                                              | —                                |

### Text

Body copy — paragraphs and inline runs of text. Use `Heading` for headings
and `Link` for anything that navigates.

| Prop      | Type                        | Default     |
| --------- | ----------------------------- | ----------- |
| `as`      | `"p" \| "span" \| "div"`     | `"p"`       |
| `size`    | `"sm" \| "md" \| "lg"`       | `"md"`      |
| `variant` | `"default" \| "muted"`       | `"default"` |
| `class`   | `string`                      | —           |

### Link

An inline text link, distinct from `Button` (which is for actions styled as
buttons). `external` marks the link as leaving the site: it opens in a new
tab, gets a safe `rel`, and gains a visually-hidden hint for screen readers.

| Prop        | Type                    | Default     |
| ----------- | -------------------------- | ----------- |
| `href`      | `string` (required)        | —           |
| `variant`   | `"default" \| "muted"`     | `"default"` |
| `underline` | `"always" \| "hover"`      | `"hover"`   |
| `external`  | `boolean`                  | `false`     |
| `class`     | `string`                    | —           |

## Theming

Every component reads color/typography/radius from CSS custom properties,
each with a neutral fallback so components render sensibly with no theme
applied at all. No client colors, fonts, or branding are hardcoded anywhere
in this package — a client site themes these primitives by redefining the
variables below (typically on `:root` in the app's global stylesheet).

| Variable                  | Used for                              | Fallback             |
| -------------------------- | ---------------------------------------- | --------------------- |
| `--ui-font-sans`           | font-family for all text                 | system sans-serif stack |
| `--ui-color-fg`             | default text color                       | `#111827`             |
| `--ui-color-muted-fg`       | secondary/supporting text                | `#6b7280`              |
| `--ui-color-bg`             | card/surface background                  | `#ffffff`              |
| `--ui-color-border`         | borders, neutral badge background        | `#e5e7eb`              |
| `--ui-color-primary`        | primary action color (buttons, links)    | `#2563eb`              |
| `--ui-color-primary-fg`     | text/icon color on a solid primary surface | `#ffffff`            |
| `--ui-color-success`        | success badge                            | `#16a34a`              |
| `--ui-color-warning`        | warning badge                            | `#d97706`              |
| `--ui-color-danger`         | danger badge                             | `#dc2626`              |
| `--ui-radius`               | small radius (buttons, badges)           | `0.5rem`               |
| `--ui-radius-lg`            | large radius (cards)                     | `0.75rem`              |

Example client theme, set once in the app's global stylesheet:

```css
:root {
  --ui-font-sans: "Inter", system-ui, sans-serif;
  --ui-color-primary: #0f766e;
  --ui-color-primary-fg: #ffffff;
}
```

## Type-checking

This package has no `.astro`/`.ts` build step — it's consumed as source by
the Vite/Astro pipeline of whichever app imports it. `pnpm check` here runs
`astro check`, since plain `tsc` does not understand `.astro` files.

## Deliberately not included in v0.1

`Hero`, `Navbar`, `Footer`, forms, chatbot, gallery, testimonials, FAQ, and
anything client-specific belong to `packages/blocks` (composed from these
primitives) or a client app, not this package.
