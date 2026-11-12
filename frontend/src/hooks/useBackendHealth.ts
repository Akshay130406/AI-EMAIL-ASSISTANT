import { useEffect, useState } from "react";
import { getHealth } from "../services/api";

type HealthState =
  | { status: "checking" }
  | { status: "online" }
  | { status: "offline"; message: string };

export function useBackendHealth(): HealthState {
  const [health, setHealth] = useState<HealthState>({ status: "checking" });

  useEffect(() => {
    let active = true;

    getHealth()
      .then((response) => {
        if (active) {
          setHealth(
            response.status === "ok"
              ? { status: "online" }
              : { status: "offline", message: "Unexpected health response" },
          );
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setHealth({
            status: "offline",
            message:
              error instanceof Error ? error.message : "Unable to reach backend",
          });
        }
      });

    return () => {
      active = false;
    };
  }, []);

  return health;
}
