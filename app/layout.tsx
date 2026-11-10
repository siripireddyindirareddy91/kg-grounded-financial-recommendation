import './globals.css';
import type { Metadata } from 'next';
export const metadata: Metadata = {title:'FinGraph AI · Intelligence, connected.',description:'Graph-grounded financial suitability intelligence. An educational demonstration with transparent evidence and human review.'};
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en"><body>{children}</body></html>}
