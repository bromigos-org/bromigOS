import type { AppProps } from "next/app";
import Head from "next/head";
import "@/styles/fonts.css";
import "@/styles/tokens.css";
import "@/styles/base.css";
import "@/styles/shell.css";
import "@/styles/activity.css";
import "@/styles/home.css";
import "@/styles/machine.css";
import "@/styles/data.css";
import "@/styles/supply.css";
import "@/styles/app.css";

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        <title>Lab board</title>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
      </Head>
      <Component {...pageProps} />
    </>
  );
}
