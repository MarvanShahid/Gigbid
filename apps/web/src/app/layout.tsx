import "./globals.css";
import Nav from "@/components/Nav";
import DegradedBanner from "@/components/DegradedBanner";

export const metadata = { title: "GigBid", description: "Multi-agent freelancer copilot" };
export const viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Nav />
          <main>
            <DegradedBanner />
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
