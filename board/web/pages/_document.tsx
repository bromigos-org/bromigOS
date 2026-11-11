// The one HTML document. No inline script runs and no inline style is served, so the page works
// under the service's Content-Security-Policy: default-src 'self' (DESIGN.md §1). The icon
// sprite is plain SVG markup. The world defaults to the Wick until the door names the server's.
import { Head, Html, Main, NextScript } from "next/document";
import { SPRITE } from "@/components/sprite";

export default function Document() {
  return (
    <Html lang="en" data-world="wick">
      <Head>
        <meta name="color-scheme" content="dark" />
        <meta name="referrer" content="no-referrer" />
        <meta name="robots" content="noindex" />
      </Head>
      <body>
        <svg className="sprite" width="0" height="0" aria-hidden="true" focusable="false" dangerouslySetInnerHTML={{ __html: SPRITE }} />
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
