"use client";

import { useParams } from "next/navigation";
import { ClinicDetail } from "./clinic-detail";

export default function ClinicPage() {
  const { id } = useParams<{ id: string }>();
  return <ClinicDetail id={id} />;
}
