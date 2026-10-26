<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

- Visual system lives in DESIGN.md and src/components/console/ui.tsx; new screens must reuse those tokens and primitives so the site and console stay consistent.
- Logged-in console pages are children of the pathless `_console` layout (sidebar + auth gate); the root hides the marketing header/footer for them.
- The 3D logo is built from code in src/components/brand/VantyrLogo3D.tsx and only shown on pages that skip server rendering — 3D needs the browser.
