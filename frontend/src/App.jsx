import { useEffect, useState } from "react";
import { Agentation } from "agentation";

function readAgentationConfig() {
  const rawConfig = window.__AGENTATION_CONFIG__ || {};
  const endpoint = typeof rawConfig.endpoint === "string" && rawConfig.endpoint.trim()
    ? rawConfig.endpoint.trim()
    : "http://127.0.0.1:4747";

  return {
    enabled: rawConfig.enabled !== false,
    endpoint,
  };
}

export default function App() {
  const [serverReady, setServerReady] = useState(false);
  const config = readAgentationConfig();

  useEffect(() => {
    let active = true;

    async function checkHealth() {
      if (!config.enabled) {
        if (active) {
          setServerReady(false);
        }
        return;
      }

      try {
        const response = await fetch(`${config.endpoint}/health`);
        if (active) {
          setServerReady(response.ok);
        }
      } catch {
        if (active) {
          setServerReady(false);
        }
      }
    }

    checkHealth();

    return () => {
      active = false;
    };
  }, [config.enabled, config.endpoint]);

  if (!config.enabled || !serverReady) {
    return null;
  }

  return <Agentation endpoint={config.endpoint} className="agentation-react__toolbar" />;
}
