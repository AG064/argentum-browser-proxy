import { chromium } from 'playwright';

const url = process.argv[2] || process.argv[1];
if (!url) {
    console.error('Usage: node cloudflare.js <url>');
    process.exit(1);
}

const parsed = new URL(url);
const domain = parsed.hostname;

async function bypass() {
    console.error(`[Cloudflare] Bypassing challenge for ${domain}`);
    
    const browser = await chromium.launch({ 
        headless: true,
        args: [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-gpu'
        ]
    });
    
    const context = await browser.newContext({
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    });
    
    const page = await context.newPage();
    
    try {
        await page.goto(url, { 
            timeout: 45000, 
            waitUntil: 'domcontentloaded'
        });
        
        // Wait for any Cloudflare challenge to complete
        await page.waitForTimeout(5000);
        
        // Check if Cloudflare challenge is present
        const content = await page.content();
        const title = await page.title();
        
        if (title.toLowerCase().includes('cloudflare') || content.substring(0, 2000).toLowerCase().includes('cloudflare')) {
            console.error(`[Cloudflare] Challenge detected, waiting...`);
            for (let i = 0; i < 30; i++) {
                await page.waitForTimeout(1000);
                const newContent = await page.content();
                if (!newContent.substring(0, 1000).toLowerCase().includes('cloudflare')) {
                    break;
                }
            }
        }
        
        // Get cookies
        const cookies = await context.cookies();
        
        const result = {
            success: true,
            domain,
            cookies: cookies.map(c => ({
                name: c.name,
                value: c.value,
                domain: c.domain,
                path: c.path,
                expires: c.expires,
                httpOnly: c.httpOnly,
                secure: c.secure,
                sameSite: c.sameSite
            })),
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        };
        
        console.log(JSON.stringify(result));
        
    } catch (e) {
        console.error(`[Cloudflare] Error: ${e.message}`);
        console.log(JSON.stringify({ success: false, error: e.message }));
    } finally {
        await browser.close();
    }
}

bypass();
