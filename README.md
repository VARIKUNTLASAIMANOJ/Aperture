# Portfolio: Execution Trace

A portfolio that behaves like a running agent graph. Built with Vite and plain JavaScript, no framework.

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # static site in dist/
```

## Filling in your content

Everything the site says lives in [`src/content.js`](src/content.js). You shouldn't need to touch any other file.

- Replace each `[bracketed]` value with real text. Until you do, it shows on the page as a visible placeholder.
- Links still holding a `[slot]` render as dashed buttons that do nothing. Set a link to `null` to hide it.
- Empty an array (`[]`) to hide that section and its step in the trace rail.
- Drop your résumé and photo into `public/` and point to them: `resume: '/resume.pdf'`, `photo: '/me.jpg'`.
- Projects and internship work items list the `skills` they used. Use the exact names from the `skills` groups so the chat assistant can say where each tool was used.

### Skills

Skills glide under the hero on one endless circuit; each group gets its own color along it. Skills look like this:

```js
{ name: 'TensorFlow', level: 8, icon: 'tensorflow' }
```

- `level` is your own 1–10 rating. `null` hides the bar.
- `icon` is a [Simple Icons](https://simpleicons.org) slug (loaded from `cdn.simpleicons.org`) or a path to your own image in `public/`. Without one, the node shows the skill's initials.

### Projects

Projects open one at a time: pick a thumbnail and its details and big preview appear. Each project reads like a tool: a `signature` (for example `research(topic, persona) → Answer | Paper`), a `summary`, `tags`, and the `skills` it used. Add a `media: { src, alt }` screenshot to use as the thumbnail and preview. `architecture` draws the diagram. It's a list of layers from left to right, and every box connects to every box in the next layer:

```js
architecture: [['User'], ['API'], ['Orchestrator · LangGraph'], ['Search agent', 'Retrieval agent', 'Writer agent'], ['Postgres', 'Redis']],
```

Text after ` · ` becomes a small second line in the box.

### Certificates

Add a picture of each certificate to `public/` and set `image: '/certs/name.png'`. Until then the carousel draws a stand-in card, with the issuer's `logo` in its seal: a [Simple Icons](https://simpleicons.org) slug (`'postman'`, `'udemy'`), a file in `public/` (`'/logos/gdsc.svg'`), or an image URL. Without a logo the seal shows the issuer's initials.

### Activity trace

Set `log.githubUser` to your GitHub username and the section shows your real contribution graph. It's fetched in the visitor's browser from the public `github-contributions-api.jogruber.de` service. While it's still a `[slot]`, the dev server shows labeled sample data and production hides the section.

### The chat assistant

The robot in the corner answers visitors' questions about your work. It has two modes:

- **With Groq (recommended).** Questions go to `/api/chat` ([`server/chat.js`](server/chat.js)), which sends your knowledge base, [`kb/knowledge.md`](kb/knowledge.md), to a Groq model (`openai/gpt-oss-120b` by default, low reasoning effort, short answers) with instructions to answer only from it, never invent details, and link to sections of the page.
- **Without a key.** If the endpoint isn't set up, the chat answers on its own from `content.js` (internships, projects, tools, education, certificates, contact, about) and says when something isn't covered.

**The knowledge base** is a plain Markdown file you edit freely: add details the page doesn't show, FAQ answers (relocation, notice period, preferred roles), deeper project notes. It's read on every question, so edits apply immediately. Text in `<!-- comments -->` is stripped before the model sees it, so you can leave notes to yourself. Anything else in the file can be repeated to any visitor: keep your phone number and other private details out. It never ships to the browser.

To turn on Groq:

1. Create an API key at [console.groq.com/keys](https://console.groq.com/keys).
2. Local: paste it after `GROQ_API_KEY=` in `.env.local`. The dev server picks it up when it restarts on the change and serves `/api/chat` itself.
3. Vercel: add `GROQ_API_KEY` under Project → Settings → Environment Variables. [`api/chat.js`](api/chat.js) becomes the function, and [`vercel.json`](vercel.json) ships `kb/` with it.

To try another model, set `GROQ_MODEL` to any chat model ID from [Groq's model list](https://console.groq.com/docs/models). The endpoint caps question length and history, and rate-limits each visitor (30 questions per 10 minutes, best effort). On hosts without serverless functions (GitHub Pages and similar) the chat simply stays in on-page mode. To point it elsewhere, set `ask.endpoint` in `content.js`; `null` turns the model off.

### Contact form (EmailJS)

The form sends through [EmailJS](https://www.emailjs.com): one email to you, and an optional auto-reply to the visitor. Fill in the IDs in `.env.local` (already created, git-ignored), then restart `npm run dev`:

| Variable | Where to find it in the EmailJS dashboard |
|---|---|
| `NEXT_PUBLIC_EMAILJS_SERVICE_ID` | Email Services → your service |
| `NEXT_PUBLIC_EMAILJS_TEMPLATE_ID` | Email Templates → the template that emails you |
| `NEXT_PUBLIC_EMAILJS_AUTOREPLY_TEMPLATE_ID` | Email Templates → the auto-reply template (optional) |
| `NEXT_PUBLIC_EMAILJS_PUBLIC_KEY` | Account → Public Key |

Both templates receive these variables: `{{name}}`, `{{email}}`, `{{message}}`, `{{reply_to}}`, `{{to_name}}` and `{{time}}`. In the template that emails you, set **Reply To** to `{{email}}` so you can answer straight from your inbox. In the auto-reply template, set **To Email** to `{{email}}`.

These values are built into the page, which is how EmailJS is meant to work: the public key is public. To stop others reusing it, add your site's domain to the allowed origins in EmailJS's security settings. The form also blocks headless browsers and allows one send every 10 seconds.

When deploying, add the same four variables to your host's environment settings (on Vercel: Project → Settings → Environment Variables) and redeploy, because they're baked in at build time.

Without EmailJS IDs, the form falls back to `contact.endpoint` in `src/content.js` (any service that accepts JSON, like Formspree). With neither, the dev server pretends the send worked so you can preview the flow, and a production build shows an error that points visitors to your email.

## Deploying

`npm run build` outputs plain static files in `dist/`. The page is rendered into `index.html` at build time (so it paints before any script runs), the stylesheet is inlined, and `robots.txt`, `sitemap.xml` and link-preview tags are generated from `meta` in `content.js`: keep `meta.url` set to the live address and `meta.image` to the picture shown when the link is shared. The output works on Vercel (which also runs the chat function) or any static host. If the site will live under a subpath (like `username.github.io/portfolio/`), set `base` in `vite.config.js`.

## Design

- `PRODUCT.md`: who the site is for and what it must do.
- `DESIGN.md`: the visual system (agent colors, type, shapes, components, rules).
