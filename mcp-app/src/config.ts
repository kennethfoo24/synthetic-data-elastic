export interface Config {
  esUrl: string;
  kibanaUrl: string;
  apiKey: string;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const missing: string[] = [];

  if (!env["ES_URL"]) missing.push("ES_URL");
  if (!env["KIBANA_URL"]) missing.push("KIBANA_URL");
  if (!env["ELASTIC_API_KEY"]) missing.push("ELASTIC_API_KEY");

  if (missing.length > 0) {
    throw new Error(`Missing required env: ${missing.join(", ")}`);
  }

  return {
    esUrl: env["ES_URL"]!.replace(/\/+$/, ""),
    kibanaUrl: env["KIBANA_URL"]!.replace(/\/+$/, ""),
    apiKey: env["ELASTIC_API_KEY"]!,
  };
}
