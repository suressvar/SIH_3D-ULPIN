import { test, expect } from '@playwright/test';
import fs from 'node:fs';
test('blush layout across login, menus and mobile', async ({page})=>{
 await page.goto('/');
 await expect(page.getByRole('heading',{name:'Welcome back.'})).toBeVisible();
 await page.screenshot({path:'../output/blush/login.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 await page.screenshot({path:'../output/blush/login-mobile.png',fullPage:true});
 await page.setViewportSize({width:1440,height:960});
 const tokens=JSON.parse(fs.readFileSync('../data/ui-test/sessions.json','utf8'));
 await page.getByText('Use an existing access token').click();
 await page.getByLabel('JWT access token').fill(tokens.surveyor);
 await page.getByRole('button',{name:'Connect session'}).click();
 for(const menu of ['Home','Buildings','Validation','Reports','Settings']){
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:menu,exact:true}).click();
  await expect(page.getByRole('navigation').getByRole('button',{name:menu,exact:true})).toHaveAttribute('aria-current','page');
  await expect(page.locator('.content h1')).toBeVisible();
  if(menu==='Home') await expect(page.locator('.stats')).toBeVisible();
  await page.waitForLoadState('networkidle');
  await page.screenshot({path:`../output/blush/${menu.toLowerCase()}.png`});
 }
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
