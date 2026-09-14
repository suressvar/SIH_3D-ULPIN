import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const accounts = JSON.parse(readFileSync("../data/ui-test/demo-credentials.json", "utf8"));
for (const role of ["officer", "surveyor"]) {
  test(`local email sign-in verifies ${role} membership`, async ({ page }) => {
    await page.goto("/");
    await expect(page.getByLabel("Email", { exact: true })).toBeEnabled();
    await page.getByLabel("Email", { exact: true }).fill(`${role}@astra.test`);
    await page.getByLabel("Password", { exact: true }).fill("incorrect-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toContainText("Incorrect email or password");
    await page.getByLabel("Password", { exact: true }).fill(accounts[`${role}@astra.test`].password);
    const memberResponse = page.waitForResponse(r => r.url().endsWith("/auth/me") && r.status() === 200);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    expect((await (await memberResponse).json()).role).toBe(role);
    await expect(page.getByRole("heading", { name: "Astra VI workspace" })).toBeHidden();
  });
}
