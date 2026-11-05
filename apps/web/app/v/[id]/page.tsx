import { Verifier } from "./verifier";

export const metadata = { title: "Verify a SecurePitch dossier" };

export default async function VerifyPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <Verifier id={id} />;
}
