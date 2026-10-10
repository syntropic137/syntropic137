import { redirect } from 'next/navigation';

/** docs.syntropic137.com has no home page of its own: start at Getting Started. */
export default function HomePage() {
  redirect('/docs/guide/getting-started');
}
