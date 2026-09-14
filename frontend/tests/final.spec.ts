import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const tokens = () =>
  JSON.parse(
    fs.readFileSync(path.resolve("../data/ui-test/sessions.json"), "utf8"),
  );
const demo = JSON.parse(
  fs.readFileSync(path.resolve("../output/judge-demo/manifest.json"), "utf8"),
);
test.beforeAll(async ({ request }) => {
  test.setTimeout(120000);
  // Prepare current immutable assets through the real API/job path; preserve all history.
  const headers = { Authorization: "Bearer " + tokens().surveyor };
  const queued = await request.post("/api/v1/pipeline/jobs", {
    headers,
    data: {
      kind: "EXPORT_ASSETS",
      object_id: demo.parcel_id,
      vertical_offset_to_ellipsoid: 0,
    },
  });
  expect(queued.status()).toBe(202);
  const job = await queued.json();
  await expect
    .poll(
      async () => {
        const response = await request.get("/api/v1/processing/" + job.id, {
          headers,
        });
        const current = await response.json();
        if (current.status === "FAILED") throw new Error(current.error_message);
        return current.status;
      },
      { timeout: 90000, intervals: [1000, 2000] },
    )
    .toBe("COMPLETED");
});
async function login(page: Page, role = "surveyor") {
  await page.goto("/");
  await page.getByText("Use an existing access token").click();
  await page.getByLabel("JWT access token").fill(tokens()[role]);
  await page.getByRole("button", { name: "Connect session" }).click();
  await expect(
    page.getByRole("heading", { name: "Property workspace" }),
  ).toBeVisible();
}
async function parcel(page: Page) {
  await page.getByLabel("Global search").fill(demo.search);
  await page
    .getByLabel("Search results")
    .getByRole("button", { name: /P001/ })
    .click();
}
async function unit(page: Page, name = "A-301") {
  await page.locator(".floors").getByText("F3", { exact: true }).click();
  await page.getByRole("button", { name: "Units", exact: true }).click();
  await page.locator(".inspector .tree-item").filter({ hasText: name }).click();
  await expect(page.locator(".inspector h2")).toHaveText(name);
}
async function models(page: Page) {
  await expect
    .poll(
      async () =>
        Number(
          await page
            .getByLabel("3D cadastral viewer")
            .getAttribute("data-loaded-models"),
        ),
      { timeout: 60000 },
    )
    .toBeGreaterThan(0);
}
test("judge: ULPIN, streamed property, F3, evidence, correction, officer acceptance, history and basement", async ({
  page,
  browser,
}) => {
  test.setTimeout(240000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const loaded: string[] = [];
  page.on("response", (r) => {
    if (r.ok() && /tileset.json|\.glb/.test(r.url())) loaded.push(r.url());
  });
  await login(page);
  await parcel(page);
  await models(page);
  await expect(page.getByLabel("3D cadastral viewer")).toHaveAttribute(
    "data-renderer",
    "illustrative-exterior",
  );
  await page.getByRole("button", { name: "Volumes", exact: true }).click();
  await models(page);
  await expect(page.getByLabel("3D cadastral viewer")).toHaveAttribute(
    "data-renderer",
    "3d-tiles",
  );
  expect(loaded.some((x) => x.includes("tileset.json"))).toBe(true);
  expect(loaded.some((x) => x.includes(".glb"))).toBe(true);
  await page.screenshot({ path: "../output/final-streamed-property.png" });
  const surface = page.locator(".cesium-widget canvas");
  const rect = await surface.boundingBox();
  await surface.click({
    position: { x: rect!.width * 0.5, y: rect!.height * 0.35 },
  });
  await expect(page.locator(".inspector h2")).not.toHaveText("P001");
  await page.getByRole("button", { name: "2D", exact: true }).click();
  await expect(page.getByLabel("2D parcel map")).toBeVisible();
  await page.locator(".context .tree-item").filter({ hasText: "B01" }).click();
  await page.getByRole("button", { name: "3D", exact: true }).click();
  await models(page);
  const canvas = page.locator(".cesium-widget canvas");
  const before = await canvas.screenshot();
  await canvas.hover();
  await page.mouse.wheel(0, -100);
  await expect
    .poll(async () => !(await canvas.screenshot()).equals(before))
    .toBe(true);
  await unit(page, "A-302");
  await expect(page.locator(".inspector")).toContainText("Proposed 3D ULPIN");
  await expect(page.locator(".inspector")).not.toContainText(
    "Not issued for this geometry",
  );
  await expect(page.locator(".context")).toContainText(demo.search);
  await unit(page);
  await page.getByRole("button", { name: /Property case/ }).click();
  const panel = page.locator(".governance");
  const dl = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Download source", exact: true })
    .first()
    .click();
  const evidence = await dl;
  expect(await evidence.failure()).toBeNull();
  if (
    (await panel.getByTestId("workflow-state").textContent()) !==
    "CORRECTION REQUIRED"
  ) {
    await panel
      .getByRole("button", { name: "Correct boundary", exact: true })
      .click();
    await panel
      .getByLabel("Boundary polygon")
      .fill(
        fs.readFileSync(
          path.resolve("../output/judge-demo/conflict-A301.geojson"),
          "utf8",
        ),
      );
    await panel
      .getByLabel("Change reason")
      .fill(
        "Reintroduce disclosed synthetic overlap for a repeatable judge test; retain earlier acceptance history",
      );
    await panel
      .getByRole("button", { name: "Save record", exact: true })
      .click();
    await expect(panel.getByRole("status")).toContainText("Record saved");
  }
  await panel
    .getByRole("button", { name: "Run validation", exact: true })
    .click();
  await expect(panel.getByTestId("workflow-state")).toHaveText(
    "CORRECTION REQUIRED",
    { timeout: 30000 },
  );
  await expect(
    panel.getByText(/ERROR · EXCLUSIVE_VOLUME_OVERLAP/),
  ).toBeVisible();
  await panel
    .getByRole("button", { name: "Show affected geometry" })
    .first()
    .click();
  await expect(page.locator(".inspector .notice")).toBeVisible();
  await page.screenshot({ path: "../output/final-F3-conflict.png" });
  await panel
    .getByRole("button", { name: "Correct boundary", exact: true })
    .click();
  await panel
    .getByLabel("Boundary polygon")
    .fill(
      fs.readFileSync(
        path.resolve("../output/judge-demo/corrected-A301.geojson"),
        "utf8",
      ),
    );
  await panel
    .getByLabel("Change reason")
    .fill(
      "Reconcile synthetic A-301 east boundary against supplied plan and coordinates",
    );
  await panel.getByRole("button", { name: "Save record", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Record saved");
  await panel
    .getByRole("button", { name: "Run validation", exact: true })
    .click();
  await expect(panel.getByTestId("workflow-state")).toHaveText("VALIDATED", {
    timeout: 30000,
  });
  await panel
    .getByRole("button", { name: "Record Proposed 3D ULPIN", exact: true })
    .click();
  await expect(panel.getByRole("status")).toContainText(
    "Proposed 3D ULPIN recorded",
  );
  await panel
    .getByRole("button", { name: "Submit for review", exact: true })
    .click();
  await expect(panel.getByTestId("workflow-state")).toHaveText("REVIEW");
  const officer = await browser.newPage();
  await login(officer, "officer");
  await parcel(officer);
  await unit(officer);
  await officer.getByRole("button", { name: /Property case/ }).click();
  await officer
    .getByLabel("Decision reason")
    .fill(
      "Synthetic source, current geometry and validation inspected; prototype acceptance without legal effect",
    );
  await officer
    .getByRole("button", { name: "Accept prototype", exact: true })
    .click();
  await expect(officer.getByTestId("workflow-state")).toHaveText("ACCEPTED");
  await officer.getByText("Browse complete property history").click();
  await officer.getByLabel("History records").selectOption("audit");
  await expect(
    officer.locator(".governance details").filter({
      has: officer.getByText("Browse complete property history", {
        exact: true,
      }),
    }),
  ).toContainText("REVIEW_DECIDED");
  await officer.getByLabel("History records").selectOption("geometry_versions");
  await expect(
    officer.locator(".governance details").filter({
      has: officer.getByText("Browse complete property history", {
        exact: true,
      }),
    }),
  ).toContainText("Version");
  await officer.screenshot({ path: "../output/final-accepted-history.png" });
  await page.locator(".context .tree-item").filter({ hasText: "B01" }).click();
  await page
    .getByRole("button", { name: "Exploded floors", exact: true })
    .click();
  await models(page);
  await expect(
    page.getByRole("button", { name: "Exploded floors", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({ path: "../output/final-exploded.png" });
  await page.locator(".floors button").filter({ hasText: "B1 parki" }).click();
  await expect(page.locator(".inspector h2")).toHaveText("B1 parking");
  await expect(page.locator(".inspector")).toContainText("7 to 10 m");
  expect(errors).toEqual([]);
  await officer.close();
});
test("asset failure switches to 2D and preserves property records", async ({
  page,
}) => {
  await page.route("**/api/v1/exports/**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Test: asset unavailable" }),
    }),
  );
  await login(page);
  await parcel(page);
  await expect(
    page.getByText("3D asset unavailable. Showing the 2D cadastral view."),
  ).toBeVisible({ timeout: 40000 });
  await expect(page.getByLabel("2D parcel map")).toBeVisible();
  await unit(page);
  await expect(page.locator(".inspector")).toContainText("Proposed 3D ULPIN");
});
test("no WebGL keeps source footprints selectable and essential records usable", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      type: string,
      ...args: unknown[]
    ) {
      if (type.includes("webgl")) return null;
      return Reflect.apply(original, this, [type, ...args]);
    } as typeof original;
  });
  await login(page);
  await parcel(page);
  await expect(page.getByLabel("Basic 2D source footprint view")).toBeVisible({
    timeout: 40000,
  });
  await unit(page);
  await expect(page.locator(".inspector")).toContainText("Proposed 3D ULPIN");
  await page.screenshot({ path: "../output/final-no-webgl.png" });
});
test("4x CPU and constrained network retain low-end map and floor selection", async ({
  page,
}) => {
  test.setTimeout(180000);
  await login(page);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Performance mode").selectOption("Low-end");
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 150,
    downloadThroughput: 150000,
    uploadThroughput: 75000,
  });
  const start = Date.now();
  await parcel(page);
  await expect(page.getByLabel("2D parcel map")).toBeVisible({
    timeout: 60000,
  });
  await unit(page);
  fs.writeFileSync(
    path.resolve("../output/final-constrained-browser.json"),
    JSON.stringify(
      {
        cpuSlowdown: 4,
        latencyMs: 150,
        downloadBytesPerSecond: 150000,
        parcelToUnitMs: Date.now() - start,
        limitation:
          "Chromium synthetic throttling; not a physical low-RAM or weak-GPU benchmark",
      },
      null,
      2,
    ),
  );
  await page.screenshot({ path: "../output/final-low-end.png" });
});
