This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

## Multi-language analysis and isolated execution

The workspace supports Python, JavaScript, TypeScript, Java, C, and C++. Python static analysis uses the backend environment. The other language parsers/compilers and all program execution use an isolated Bubblewrap sandbox inside WSL2 Ubuntu.

1. Ensure WSL2 Ubuntu is installed and starts successfully.
2. From the repository root, install the runner dependencies in PowerShell:

   ```powershell
   .\runner\setup-wsl.ps1
   ```

   This installs Bubblewrap, Python 3, Node.js, TypeScript, Java, and C/C++ toolchains inside Ubuntu. It does not require Docker Desktop.
3. Start the backend and frontend using their project instructions.
4. In the app, select **Refresh runner status**. The language selector reports actual analysis and execution availability.

Submitted programs run in Bubblewrap with new user, PID, mount, network, IPC, and UTS namespaces; only read-only runtime/compiler paths and the submitted source are visible inside the sandbox. The process runs as an unprivileged UID with CPU, address-space, file-size, open-file, process-count, wall-clock, output, and 64 MiB temporary-filesystem limits. Node and JVM get larger virtual-address-space ceilings for their runtimes; their heap sizes are separately capped. Programs that exceed the runtime or output limit are stopped. The API starts the WSL runner automatically; no container image or Docker socket is required.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
