import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

test("reference layout uses a real exterior asset and working view controls", async ({
  page,
}) => {
  const tokens = JSON.parse(
    fs.readFileSync(path.resolve("../data/ui-test/sessions.json"), "utf8"),
  );
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1536, height: 1024 });
  await page.goto("/");
  await page.getByText("Use an existing access token").click();
  await page.getByLabel("JWT access token").fill(tokens.surveyor);
  await page.getByRole("button", { name: "Connect session" }).click();
  await page.getByLabel("Global search").fill("DEMO26011P0001");
  await page
    .getByLabel("Search results")
    .getByRole("button", { name: /P001/ })
    .click();
  await page.locator(".context .tree-item").filter({ hasText: "B01" }).click();
  const viewer = page.getByLabel("3D cadastral viewer");
  await expect(viewer).toHaveAttribute(
    "data-renderer",
    "illustrative-exterior",
  );
  await expect
    .poll(async () => Number(await viewer.getAttribute("data-loaded-models")), {
      timeout: 60000,
    })
    .toBeGreaterThan(0);
  await expect(page.locator(".building-summary img")).toBeVisible();
  await page.screenshot({ path: "../output/reference-redesign/dashboard.png" });
  const downloaded = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download 3D model", exact: true })
    .click();
  const model = await downloaded;
  expect(await model.failure()).toBeNull();
  expect(model.suggestedFilename()).toContain("illustrative-exterior-");
  const canvas = page.locator(".cesium-widget canvas");
  const before = await canvas.screenshot();
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect
    .poll(async () => !(await canvas.screenshot()).equals(before))
    .toBe(true);
  await page
    .getByRole("button", { name: "Reset view north", exact: true })
    .click();
  await page.getByRole("button", { name: "Footprint", exact: true }).click();
  await expect(page.locator(".context")).toContainText(
    "Recorded parcel footprint",
  );
  await page.getByRole("button", { name: "Site model", exact: true }).click();
  await expect(page.locator(".context")).toContainText("Illustrative site");
  await page.locator(".floors").getByText("F3", { exact: true }).click();
  await expect(viewer).not.toHaveAttribute(
    "data-renderer",
    "illustrative-exterior",
  );
  await page.getByRole("button", { name: "Units", exact: true }).click();
  await expect(page.locator(".inspector")).toContainText("A-301");
  expect(errors).toEqual([]);
});
