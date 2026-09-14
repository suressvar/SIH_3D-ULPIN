import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const tokens = () =>
  JSON.parse(
    fs.readFileSync(path.resolve("../data/ui-test/sessions.json"), "utf8"),
  );
async function login(page: Page, role: string) {
  await page.goto("/");
  await page.getByText("Use an existing access token").click();
  await page.getByLabel("JWT access token").fill(tokens()[role]);
  await page.getByRole("button", { name: "Connect session" }).click();
  await expect(
    page.getByRole("heading", { name: "Property workspace" }),
  ).toBeVisible();
}
async function openUnit(page: Page) {
  await page.getByLabel("Global search").fill("source pipeline parcel");
  await page
    .getByLabel("Search results")
    .getByRole("button", { name: /source pipeline parcel/ })
    .click();
  await page.locator(".floors").getByText("GF", { exact: true }).click();
  await page.getByRole("button", { name: "Units", exact: true }).click();
  await page.locator(".inspector .tree-item").first().click();
  await page.getByRole("button", { name: /Property case/ }).click();
}
test("phase 4: evidence, rights, conflict, correction, separate officer acceptance and immutable history", async ({
  page,
  browser,
  request,
}) => {
  test.setTimeout(240000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, "surveyor");
  const casePromise = page.waitForResponse(
    (r) =>
      r.url().includes("/governance/objects/") &&
      r.request().method() === "GET" &&
      r.url().includes("?") == false,
  );
  // Select via existing floor explorer; API response identifies the actual chosen unit below.
  await openUnit(page);
  await casePromise;
  const all = await request.get(
    "http://127.0.0.1:8011/api/v1/workspace/scene/b2337d02-89f9-5f34-a719-3b5f8615164b",
    { headers: { Authorization: "Bearer " + tokens().surveyor } },
  );
  const scene = (await all.json()).result;
  const selected = await page.locator(".inspector h2").textContent();
  const floor = scene.objects.find(
    (o: { kind: string; floor_number: number }) =>
      o.kind === "FLOOR" && o.floor_number === 0,
  );
  const unit = scene.objects.find(
    (o: { kind: string; parent_id: string; label: string }) =>
      o.kind === "UNIT" && o.parent_id === floor.id && o.label === selected,
  );
  expect(unit).toBeTruthy();
  const original = scene.geometries.find(
    (g: { object_id: string }) => g.object_id === unit.id,
  );
  const neighbour = scene.geometries.find((g: { object_id: string }) =>
    scene.objects.some(
      (o: { id: string; kind: string; parent_id: string }) =>
        o.id === g.object_id &&
        o.kind === "UNIT" &&
        o.parent_id === floor.id &&
        o.id !== unit.id,
    ),
  );
  const panel = page.locator(".governance");
  await panel
    .getByRole("button", { name: "Add evidence", exact: true })
    .click();
  await panel
    .getByLabel("Source document")
    .setInputFiles({
      name: "synthetic-review-evidence.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from(
        "%PDF-1.4\n% Demo / Synthetic Dataset\n1 0 obj<</Type/Catalog>>endobj\n%%EOF",
      ),
    });
  await panel
    .getByLabel("Evidence description")
    .fill("Demo / Synthetic Dataset — phase 4 correction evidence");
  await panel.getByRole("button", { name: "Save record", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Record saved");
  await panel
    .getByRole("button", { name: "Record right", exact: true })
    .click();
  await panel
    .getByLabel("Provided party reference")
    .fill("SYNTHETIC PARTY — no real owner");
  await panel
    .getByLabel("Right description")
    .fill("Synthetic recorded ownership assertion for review exercise");
  await panel.getByRole("button", { name: "Save record", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Record saved");
  async function correct(poly: unknown, why: string) {
    await panel
      .getByRole("button", { name: "Correct boundary", exact: true })
      .click();
    await panel.getByLabel("Boundary polygon").fill(JSON.stringify(poly));
    await panel.getByLabel("Change reason").fill(why);
    await panel
      .getByRole("button", { name: "Save record", exact: true })
      .click();
    await expect(panel.getByRole("status")).toContainText("Record saved");
  }
  await correct(
    neighbour.footprint,
    "Synthetic deliberate overlapping boundary for validation exercise",
  );
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
  await page.screenshot({ path: "../output/phase4-conflict.png" });
  await correct(
    original.footprint,
    "Restore supplied synthetic source boundary after overlap inspection",
  );
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
  await openUnit(officer);
  await officer
    .getByLabel("Decision reason")
    .fill(
      "Synthetic geometry and supporting evidence reviewed; prototype acceptance only",
    );
  await officer
    .getByRole("button", { name: "Accept prototype", exact: true })
    .click();
  await expect(officer.getByTestId("workflow-state")).toHaveText("ACCEPTED");
  await officer.screenshot({ path: "../output/phase4-accepted.png" });
  const report = await request.get(
    "http://127.0.0.1:8011/api/v1/governance/objects/" + unit.id,
    { headers: { Authorization: "Bearer " + tokens().officer } },
  );
  const data = (await report.json()).result;
  expect(data.state).toBe("ACCEPTED");
  expect(data.geometry_versions.length).toBeGreaterThanOrEqual(3);
  expect(
    data.workflow.map((e: { after_state: string }) => e.after_state),
  ).toEqual(
    expect.arrayContaining([
      "DRAFT",
      "VALIDATION",
      "CORRECTION_REQUIRED",
      "VALIDATED",
      "REVIEW",
      "ACCEPTED",
    ]),
  );
  expect(
    data.audit.some((e: { action: string }) => e.action === "REVIEW_DECIDED"),
  ).toBeTruthy();
  expect(
    data.identity_versions.some(
      (i: { geometry_id: string }) => i.geometry_id === data.geometry.id,
    ),
  ).toBeTruthy();
  const denied = await request.post(
    "http://127.0.0.1:8011/api/v1/pipeline/validate/" + unit.id,
    { headers: { Authorization: "Bearer " + tokens().viewer }, data: {} },
  );
  expect(denied.status()).toBe(403);
  expect(errors).toEqual([]);
  await officer.close();
});
