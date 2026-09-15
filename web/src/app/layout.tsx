import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans, Sora } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

// Two faces, both variable and both subset to latin: Sora carries headings and
// figures with a bit of character, Jakarta does the reading. Loaded through
// next/font so they are self-hosted and there is no layout shift on first paint.
const ui = Plus_Jakarta_Sans({
  variable: "--font-ui",
  subsets: ["latin"],
  display: "swap",
});

const display = Sora({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Grow Vyaapar",
  description:
    "Billing, inventory, customers and an autonomous marketing agent for Indian local retail.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#faf7f2" },
    { media: "(prefers-color-scheme: dark)", color: "#16130f" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-IN" className={`${ui.variable} ${display.variable} h-full`}>
      <body className="min-h-full antialiased">
        {/* The first thing in the tab order on every page: a keyboard user
            should not have to walk the whole sidebar to reach the content. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-ink"
        >
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
