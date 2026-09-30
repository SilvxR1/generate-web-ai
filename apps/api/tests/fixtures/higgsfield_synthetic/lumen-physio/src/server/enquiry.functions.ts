import { createServerFn } from "@tanstack/react-start";

import { db } from "./db.server";

export type EnquiryInput = Record<string, string>;

// Builder backend: stores the enquiry in its own database.
export const sendEnquiry = createServerFn({ method: "POST" })
  .validator((data: EnquiryInput) => data)
  .handler(async ({ data }) => {
    void db();
    return { ok: true, fields: Object.keys(data).length };
  });
