"use client";

import { useParams } from "next/navigation";
import { Wizard } from "@/components/wizard/wizard";

export default function ConfigurePage() {
  const { id } = useParams<{ id: string }>();
  return <Wizard clinicId={id} />;
}
