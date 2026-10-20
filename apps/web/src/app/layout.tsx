import type { Metadata } from 'next';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import './globals.css';

export const metadata: Metadata = {
  title: 'Worldsim',
  description: 'Prompt-driven world event simulator. Outputs are simulations, not forecasts or advice.',
};

// Applies the saved theme before first paint; default is light.
const themeScript = `try{var t=localStorage.getItem('worldsim-theme');if(t==='dark')document.documentElement.setAttribute('data-theme','dark')}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable} h-full`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="h-full bg-bg text-ink">{children}</body>
    </html>
  );
}
