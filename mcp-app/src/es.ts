import { Client } from "@elastic/elasticsearch";
import type { Config } from "./config.js";

export function createEsClient(config: Config): Client {
  return new Client({
    node: config.esUrl,
    auth: {
      apiKey: config.apiKey,
    },
    requestTimeout: 30000,
  });
}
