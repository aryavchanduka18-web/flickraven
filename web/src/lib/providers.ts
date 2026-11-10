// TMDB tells us WHICH services carry a title, but gives no link to the title on each service. So a service button
// opens that service's own search for the title, which is honest: it is a search link, not a confirmed page.
const SEARCH: [RegExp, (q: string) => string][] = [
  [/netflix/i, (q) => `https://www.netflix.com/search?q=${q}`],
  [/amazon prime|prime video/i, (q) => `https://www.primevideo.com/search/?phrase=${q}`],
  [/amazon video|amazon/i, (q) => `https://www.primevideo.com/search/?phrase=${q}`],
  [/hotstar|disney/i, (q) => `https://www.hotstar.com/in/search?q=${q}`],
  [/youtube/i, (q) => `https://www.youtube.com/results?search_query=${q}`],
  [/apple tv/i, (q) => `https://tv.apple.com/search?term=${q}`],
  [/zee5/i, (q) => `https://www.zee5.com/search?q=${q}`],
  [/sony ?liv/i, (q) => `https://www.sonyliv.com/search?q=${q}`],
  [/jio ?cinema/i, (q) => `https://www.jiocinema.com/search/${q}`],
  [/mx player/i, (q) => `https://www.mxplayer.in/search?q=${q}`],
  [/crunchyroll/i, (q) => `https://www.crunchyroll.com/search?q=${q}`],
  [/mubi/i, (q) => `https://mubi.com/en/search/films?query=${q}`],
  [/hulu/i, (q) => `https://www.hulu.com/search?q=${q}`],
  [/\bmax\b|hbo/i, (q) => `https://www.max.com/search?q=${q}`],
  [/peacock/i, (q) => `https://www.peacocktv.com/search?q=${q}`],
  [/google play/i, (q) => `https://play.google.com/store/search?q=${q}&c=movies`],
];

/** Where a service button leads: that service's search for the title when we know its address, otherwise a web
 *  search for "<title> <service>". `fallback` (JustWatch's page for the title, from TMDB) is the last resort. */
export function providerSearchUrl(service: string, title: string): string {
  const q = encodeURIComponent(title);
  for (const [re, build] of SEARCH) if (re.test(service)) return build(q);
  return `https://www.google.com/search?q=${encodeURIComponent(`${title} watch on ${service}`)}`;
}
