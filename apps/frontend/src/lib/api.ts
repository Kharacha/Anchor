// frontend/src/lib/api.ts

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

if (!API_BASE) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not set");
}

export async function createSession(tier: "free" | "paid" = "free") {
    const res = await fetch(`${API_BASE}/v1/sessions`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ tier }),
    });

    if (!res.ok) {
        const text = await res.text();
        throw new Error(`createSession failed: ${res.status} ${text}`);
    }

    return res.json();
}
