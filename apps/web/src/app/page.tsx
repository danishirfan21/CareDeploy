import { ConnectivityStatus } from "./status";

export default function Home() {
  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="mb-4 text-2xl font-semibold">CareDeploy</h1>
      <ConnectivityStatus />
    </main>
  );
}
