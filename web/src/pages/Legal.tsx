import type { ReactNode } from "react";
import { Link } from "react-router-dom";

const UPDATED = "4 November 2026";
const ISSUES = "https://github.com/aryavchanduka18-web/flickraven/issues";

function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-2xl px-4 pt-28 text-sm leading-relaxed text-white/80 md:pt-32">
      <h1 className="font-display text-3xl font-extrabold text-white">{title}</h1>
      <p className="mt-2 text-xs text-muted">Last updated {UPDATED}</p>
      <div className="mt-8 space-y-6 [&_h2]:font-display [&_h2]:text-lg [&_h2]:font-bold [&_h2]:text-white [&_li]:ml-5 [&_li]:list-disc [&_a]:underline">
        {children}
      </div>
    </article>
  );
}

export function Privacy() {
  return (
    <Page title="Privacy policy">
      <p>
        FlickRaven is a free movie recommendation website run by one person as a personal project. It does not stream
        films, show ads, or sell or share your data with anyone.
      </p>
      <section>
        <h2>What we store</h2>
        <ul>
          <li>Your email address, the name you choose, and your password stored as a one-way hash (we cannot read it).</li>
          <li>What you tell us about your taste: onboarding picks, languages and genres, ratings, likes and dislikes (with the reason, if you give one), My List and films marked as watched.</li>
          <li>Films you open or click in search, and the recommendations shown to you, so the site can learn your taste. Records of recommendations shown are deleted after 60 days.</li>
          <li>If you import a Letterboxd or IMDb file, only the ratings that match our catalog are kept. The file itself is not stored.</li>
        </ul>
        <p className="mt-2">We do not collect your location, contacts, or payment details.</p>
      </section>
      <section>
        <h2>Guests</h2>
        <p>If you browse without an account, the same data is kept under a guest session. A guest session with no activity for 30 days is deleted automatically, with everything in it.</p>
      </section>
      <section>
        <h2>Cookies</h2>
        <p>One cookie keeps you signed in (or keeps your guest session). There are no advertising or tracking cookies and no third-party analytics.</p>
      </section>
      <section>
        <h2>Where it is kept and who else is involved</h2>
        <ul>
          <li>The website runs on Render and the database on Neon, both in Singapore.</li>
          <li>Posters and photos load directly from The Movie Database (TMDB), so TMDB can see your IP address when images load.</li>
          <li>The site owner can see overall usage numbers (for example, how many people signed up this week), not what any one person watches.</li>
        </ul>
      </section>
      <section>
        <h2>Your choices</h2>
        <ul>
          <li>You can change or remove any rating, like, list entry or watched mark at any time.</li>
          <li>You can delete your account on the <Link to="/account">Account</Link> page. This removes your account and everything linked to it immediately and for good.</li>
          <li>There is no password reset, because FlickRaven does not send emails. Keep your password safe.</li>
        </ul>
      </section>
      <section>
        <h2>Children</h2>
        <p>If you are under 18, use FlickRaven only with a parent's or guardian's permission.</p>
      </section>
      <section>
        <h2>Questions and changes</h2>
        <p>Ask a question by <a href={ISSUES} target="_blank" rel="noreferrer">opening an issue on GitHub</a>. If this policy changes, the date at the top changes too.</p>
      </section>
    </Page>
  );
}

export function Terms() {
  return (
    <Page title="Terms of use">
      <p>By using FlickRaven you agree to these terms. They are short on purpose.</p>
      <section>
        <h2>What FlickRaven is</h2>
        <p>
          A free website that recommends movies. It does not stream or sell films. Recommendations and Match % are
          estimates from a computer model and can be wrong. The service is provided as it is, with no guarantee that it
          will always be available or that your data will never be lost.
        </p>
      </section>
      <section>
        <h2>Your account</h2>
        <ul>
          <li>Give a real email address you control, and keep your password safe. It cannot be reset.</li>
          <li>One person per account. You are responsible for what happens under your account.</li>
          <li>You can delete your account at any time from the <Link to="/account">Account</Link> page.</li>
        </ul>
      </section>
      <section>
        <h2>Fair use</h2>
        <ul>
          <li>Do not use scripts or bots to create accounts, send ratings, or copy the catalog.</li>
          <li>Do not try to break, overload or get around the site's security or limits.</li>
          <li>Accounts that break these rules may be removed without notice.</li>
        </ul>
      </section>
      <section>
        <h2>Film data</h2>
        <p>
          Film details and images come from <a href="https://www.themoviedb.org" target="_blank" rel="noreferrer">TMDB</a>.
          This product uses the TMDB API but is not endorsed or certified by TMDB. Ratings used to train the models come
          from MovieLens (GroupLens Research) and awards from Wikidata. Which Asian dramas go together was learned from
          the public "MyDramaList ratings" dataset on Kaggle (lists originating from MyDramaList.com); only the learned
          similarities between shows are kept here, none of that dataset's users. All film titles, posters and artwork
          belong to their owners.
        </p>
      </section>
      <section>
        <h2>Changes</h2>
        <p>These terms may change. The date at the top shows the latest version. See also the <Link to="/privacy">Privacy policy</Link>.</p>
      </section>
    </Page>
  );
}
