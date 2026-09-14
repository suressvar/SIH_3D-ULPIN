import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const sessions = () =>
  JSON.parse(
    fs.readFileSync(path.resolve("../data/ui-test/sessions.json"), "utf8"),
  );
test("phase 3: real API navigation, picking controls, modes and reports", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByText("Use an existing access token").click();
  await page.getByLabel("JWT access token").fill(sessions().surveyor);
  await page.getByRole("button", { name: "Connect session" }).click();
  await expect(
    page.getByRole("heading", { name: "Property workspace" }),
  ).toBeVisible();
  await page.getByLabel("Global search").fill("source pipeline parcel");
  await page.getByLabel("Search results").getByRole("button", { name: /source pipeline parcel/ }).click();
  await expect(page.getByLabel("3D cadastral viewer")).toBeVisible();
  const sceneResponse = await page.request.get("/api/v1/workspace/scene/b2337d02-89f9-5f34-a719-3b5f8615164b", {headers:{Authorization:"Bearer "+sessions().surveyor}});
  const currentScene = (await sceneResponse.json()).result;
  const currentAssets = currentScene.objects.filter((o:{id:string})=>currentScene.asset?.files[o.id+".glb"] && currentScene.asset.snapshot[o.id]===currentScene.geometries.find((g:{object_id:string;id:string})=>g.object_id===o.id)?.id).length;
  expect(currentAssets).toBeGreaterThan(0);

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
    .toBe(currentAssets);
  await page.screenshot({ path: "../output/phase3-workspace.png" });
  const normal = await page.getByLabel("3D cadastral viewer").screenshot();
  await page
    .getByRole("button", { name: "Exploded floors", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Exploded floors", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page
    .getByRole("button", { name: "Cross-section", exact: true })
    .click();
  await page.getByLabel("Slice position").fill("6");
  await expect.poll(async()=> (await page.getByLabel("3D cadastral viewer").screenshot()).equals(normal)).toBe(false);
  await page.screenshot({path:"../output/phase3-exploded-section.png"});
  await page.locator(".floors").getByText("GF", { exact: true }).click();
  await expect(
    page.locator(".floors").getByText("GF", { exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Units", exact: true }).click();
  const units = page.locator(".inspector .tree-item");
  await expect(units).toHaveCount(2);
  await units.first().click();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(
    page.getByText("Proposed 3D ULPIN", { exact: true }).last(),
  ).toBeVisible();
  await page.getByRole("button", { name: "2D", exact: true }).click();
  await expect(page.getByLabel("2D parcel map")).toBeVisible();
  await page.getByRole("button", { name: "3D", exact: true }).click();
  await expect(page.getByLabel("3D cadastral viewer")).toBeVisible();
  await page.getByLabel("Performance mode").selectOption("Low-end");
  await page.getByRole("button", { name: "Reset view north" }).click();
  await page.getByRole("button", { name: "Buildings", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Buildings", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Validation", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Validation workspace" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Inspect conflict" }).first().click();
  await expect(page.locator(".inspector .notice")).toBeVisible();
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await page.getByRole("button", { name: "Generate property report" }).click();
  await expect(page.locator(".case-report")).toContainText("Property report");
  await expect(page.locator(".case-report")).toContainText("Proposed 3D ULPIN");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Control+k");
  await expect(page.getByLabel("Global search")).toBeFocused();
  expect(errors).toEqual([]);
});


test("responsive GIS keeps the viewer usable at target sizes",async({page})=>{
 await page.goto("/");await page.getByText("Use an existing access token").click();await page.getByLabel("JWT access token").fill(sessions().surveyor);await page.getByRole("button",{name:"Connect session"}).click();
 await page.getByLabel("Global search").fill("Suggested building 1");await page.getByLabel("Search results").getByRole("button",{name:/Suggested building 1/}).click();
 await expect(page.getByLabel("3D cadastral viewer")).toBeVisible();
 for(const [width,height] of [[1366,768],[1440,900],[1920,1080]]){
  await page.setViewportSize({width,height});
  const rect=await page.locator(".workspace-view").boundingBox();
  expect(rect!.width).toBeGreaterThan(450);expect(rect!.height).toBeGreaterThan(400);
  expect(rect!.y+rect!.height).toBeLessThanOrEqual(height+2);
  await expect(page.getByLabel("Global search")).toBeInViewport();
 }
 await page.getByRole("button",{name:"View floors",exact:true}).click();await expect(page.locator(".inspector .tree-item")).toHaveCount(5);
 await page.screenshot({path:"../output/phase3-building.png"});
});
