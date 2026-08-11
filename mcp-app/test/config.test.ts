import { describe, it, expect } from "vitest";
import { loadConfig } from "../src/config.js";

describe("loadConfig", () => {
  const validEnv = {
    ES_URL: "https://my-es.example.com",
    KIBANA_URL: "https://my-kibana.example.com",
    ELASTIC_API_KEY: "supersecretkey",
  };

  it("returns config when all env vars are set", () => {
    const config = loadConfig(validEnv);
    expect(config.esUrl).toBe("https://my-es.example.com");
    expect(config.kibanaUrl).toBe("https://my-kibana.example.com");
    expect(config.apiKey).toBe("supersecretkey");
  });

  it("strips trailing slashes from esUrl and kibanaUrl", () => {
    const env = {
      ES_URL: "https://my-es.example.com///",
      KIBANA_URL: "https://my-kibana.example.com/",
      ELASTIC_API_KEY: "mykey",
    };
    const config = loadConfig(env);
    expect(config.esUrl).toBe("https://my-es.example.com");
    expect(config.kibanaUrl).toBe("https://my-kibana.example.com");
  });

  it("throws when ES_URL is missing and names it in the error", () => {
    const env = { KIBANA_URL: validEnv.KIBANA_URL, ELASTIC_API_KEY: validEnv.ELASTIC_API_KEY };
    expect(() => loadConfig(env)).toThrowError(/ES_URL/);
  });

  it("throws when KIBANA_URL is missing and names it in the error", () => {
    const env = { ES_URL: validEnv.ES_URL, ELASTIC_API_KEY: validEnv.ELASTIC_API_KEY };
    expect(() => loadConfig(env)).toThrowError(/KIBANA_URL/);
  });

  it("throws when ELASTIC_API_KEY is missing and names it in the error", () => {
    const env = { ES_URL: validEnv.ES_URL, KIBANA_URL: validEnv.KIBANA_URL };
    expect(() => loadConfig(env)).toThrowError(/ELASTIC_API_KEY/);
  });

  it("names ALL missing vars in a single error", () => {
    expect(() => loadConfig({})).toThrowError(
      /Missing required env: ES_URL, KIBANA_URL, ELASTIC_API_KEY/
    );
  });

  it("error message does not contain the API key value", () => {
    const secretKey = "my-very-secret-api-key-value-12345";
    const env = {
      ES_URL: "",
      KIBANA_URL: validEnv.KIBANA_URL,
      ELASTIC_API_KEY: secretKey,
    };
    let thrownMessage = "";
    try {
      loadConfig(env);
    } catch (e) {
      if (e instanceof Error) thrownMessage = e.message;
    }
    expect(thrownMessage).toBeTruthy();
    expect(thrownMessage).not.toContain(secretKey);
  });
});
