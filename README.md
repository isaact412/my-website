# Carolina Care

**Healthcare is One Call Away.**

Carolina Care is a medical transportation concept connecting rural and underserved South Carolina communities with hospitals and specialists. This repository contains the full marketing/demo website — a static, no-build site ready for GitHub Pages.

## What's here

- `index.html` — Homepage
- `patients.html` — For Patients: ride request form, accessibility options, example cost calculator
- `hospitals.html` — For Hospitals: the problem, the solution, partnership request form
- `route-demo.html` — Interactive animated Charleston → Aiken route demonstration
- `about.html` — Mission, model, approach
- `contact.html` — General contact form + advertiser inquiry form
- `privacy.html`, `terms.html` — Legal pages
- `404.html` — Not-found page
- `assets/css/styles.css` — All site styling
- `assets/js/main.js` — Navigation, forms, validation, calculator
- `assets/js/route-demo.js` — Route demo animation logic
- `assets/img/` — Logo/favicon

No build step, no dependencies, no framework — plain HTML/CSS/JS.

## Previewing locally

Just open `index.html` in a browser, or for the most accurate preview, serve the folder locally:

```bash
python3 -m http.server 8000
```

Then visit `http://localhost:8000`.

## Publishing on GitHub Pages

1. Push this repository to GitHub (already done if you're reading this on GitHub).
2. In the repository, go to **Settings → Pages**.
3. Under **Build and deployment → Source**, choose **Deploy from a branch**.
4. Choose the branch this code is on (e.g. `main`) and the `/ (root)` folder, then **Save**.
5. GitHub will give you a live URL (usually `https://<username>.github.io/<repo-name>/`) within a minute or two.

No further configuration is needed — there's no build process to run.

## About form submissions (important)

GitHub Pages only serves static files; it can't run a database or server-side code. So right now, submitting a form:

- Validates every field in the browser (required fields, email format, phone format)
- Shows a real loading state, then a real success confirmation
- Saves the submission in **your own browser's local storage** (`localStorage`) as a working demonstration — this is not sent anywhere or visible to anyone else

**To actually collect and centrally store ride requests, hospital inquiries, and advertising inquiries** (so a real person can see and act on them), you'll eventually need a backend. Reasonable low-effort options:

- A form backend service (e.g. Formspree, Getform) — emails you each submission, minimal setup, no code changes beyond the form's `action` attribute
- Supabase or a similar hosted database + a few lines of JavaScript to `POST` the form data
- A small serverless function (e.g. on Netlify/Vercel) if you outgrow GitHub Pages

Everything else on this site — navigation, phone links, the cost calculator, and the route demo — is fully functional today with no backend required.
