"use client";

import { use, useEffect, useMemo, useState } from "react";
import { Package, Pencil, Plus, Search } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR, TRowHeader } from "@/components/ui/table";
import { Pagination } from "@/components/ui/pagination";
import { Modal } from "@/components/ui/dialog";
import { Toggle } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { ProductForm } from "@/components/products/product-form";
import { useCategories, useCreateProduct, useProducts, useUpdateProduct } from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { useSession, canManage } from "@/lib/session";
import { money, quantity, count } from "@/lib/format";
import type { Product } from "@/lib/types";

export default function ProductsPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const session = useSession();
  const toast = useToast();
  const manager = canManage(session.user);

  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Product | null>(null);
  const [adding, setAdding] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Each filter change resets to page one as part of the change itself, not in
  // an effect watching for it - otherwise a search with two matches made from
  // page nine returns nothing.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const query = useMemo(
    () => ({
      q: debounced,
      categoryId,
      includeInactive,
      limit: pageSize,
      offset: (page - 1) * pageSize,
    }),
    [debounced, categoryId, includeInactive, pageSize, page],
  );

  const products = useProducts(storeId, query);
  const categories = useCategories(storeId);
  const create = useCreateProduct(storeId);
  const update = useUpdateProduct(storeId);

  const data = products.data;

  return (
    <>
      <PageHeader
        title="Products"
        subtitle={`The catalog for ${store.store_name}. Prices include the GST rate set per product.`}
        actions={
          manager ? (
            <Button variant="primary" onClick={() => setAdding(true)}>
              <Plus className="size-4" aria-hidden />
              Add product
            </Button>
          ) : null
        }
      />

      <Card>
        <Card.Header>
          <div className="flex flex-1 flex-wrap items-center gap-2">
            <div className="relative min-w-56 flex-1">
              <Search
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3"
                aria-hidden
              />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                placeholder="Search by name or SKU across the whole catalog"
                aria-label="Search products"
                className="h-9 w-full rounded-lg border border-line bg-surface pr-3 pl-9 text-sm text-ink placeholder:text-ink-3 hover:border-line-strong"
              />
            </div>

            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              <span className="sr-only sm:not-sr-only">Category</span>
              <select
                value={categoryId ?? ""}
                onChange={(event) => {
                  setCategoryId(
                    event.currentTarget.value ? Number(event.currentTarget.value) : null,
                  );
                  setPage(1);
                }}
                className="h-9 rounded-lg border border-line bg-surface px-2 text-sm text-ink hover:border-line-strong"
              >
                <option value="">All categories</option>
                {(categories.data ?? []).map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </label>

            <Toggle
              label="Show inactive"
              checked={includeInactive}
              onChange={(next) => {
                setIncludeInactive(next);
                setPage(1);
              }}
            />
          </div>
        </Card.Header>

        {products.isPending ? (
          <SkeletonRows rows={8} columns={6} />
        ) : products.isError ? (
          <ErrorState
            title="Unable to load products"
            detail={products.error.message}
            onRetry={() => void products.refetch()}
          />
        ) : data === undefined ? null : data.items.length === 0 ? (
          <EmptyState
            icon={<Package className="size-5" aria-hidden />}
            title={debounced ? "No product matches that search" : "The catalog is empty"}
            hint={
              debounced
                ? "The search covers every product in this store, not just this page."
                : `Add the first product to ${store.store_name}.`
            }
            action={
              debounced ? (
                <Button variant="secondary" onClick={() => setSearch("")}>
                  Clear search
                </Button>
              ) : manager ? (
                <Button variant="primary" onClick={() => setAdding(true)}>
                  <Plus className="size-4" aria-hidden />
                  Add product
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <Table caption="Products in this store">
              <THead>
                <TH>Product</TH>
                <TH>Category</TH>
                <TH align="right">Cost</TH>
                <TH align="right">Price</TH>
                <TH align="right">GST</TH>
                <TH align="right">In stock</TH>
                {manager ? <TH align="right">Edit</TH> : null}
              </THead>
              <TBody>
                {data.items.map((product) => {
                  const low = product.qty_on_hand <= product.reorder_point;
                  return (
                    <TR key={product.id}>
                      <TRowHeader>
                        <span className="block truncate">{product.name}</span>
                        <span className="block font-mono text-[11px] font-normal text-ink-3">
                          {product.sku}
                          {product.is_active ? null : " · inactive"}
                        </span>
                      </TRowHeader>
                      <TD className="text-ink-2">
                        {product.category_name ?? <span className="text-ink-3">—</span>}
                      </TD>
                      <TD align="right" numeric className="text-ink-2">
                        {money(product.cost_price)}
                      </TD>
                      <TD align="right" numeric className="font-medium">
                        {money(product.sell_price)}
                      </TD>
                      <TD align="right" numeric className="text-ink-2">
                        {product.gst_rate}%
                      </TD>
                      <TD align="right">
                        {low ? (
                          <Badge tone={product.qty_on_hand <= 0 ? "danger" : "warning"}>
                            {quantity(product.qty_on_hand, product.unit_label)}
                          </Badge>
                        ) : (
                          <span className="tnum">
                            {quantity(product.qty_on_hand, product.unit_label)}
                          </span>
                        )}
                      </TD>
                      {manager ? (
                        <TD align="right">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setEditing(product)}
                            aria-label={`Edit ${product.name}`}
                          >
                            <Pencil className="size-3.5" aria-hidden />
                          </Button>
                        </TD>
                      ) : null}
                    </TR>
                  );
                })}
              </TBody>
            </Table>

            <Card.Footer>
              <Pagination
                page={data.page}
                pageSize={data.pageSize}
                total={data.total}
                totalPages={data.totalPages}
                returned={data.items.length}
                hasNext={data.hasNext}
                noun="products"
                onPageChange={setPage}
                onPageSizeChange={(size) => {
                  setPageSize(size);
                  setPage(1);
                }}
              />
            </Card.Footer>
          </>
        )}
      </Card>

      <Modal
        open={adding}
        onClose={() => {
          setAdding(false);
          setFormError(null);
        }}
        title={`Add a product to ${store.store_name}`}
        description={`Quantities are in ${store.unit_labels.default}, this store's own unit.`}
      >
        <ProductForm
          categories={categories.data ?? []}
          unitLabel={store.unit_labels.default}
          productSchema={store.product_schema}
          busy={create.isPending}
          serverError={formError}
          onCancel={() => {
            setAdding(false);
            setFormError(null);
          }}
          onSubmit={(body) => {
            setFormError(null);
            create.mutate(body, {
              onSuccess: (product) => {
                setAdding(false);
                setSearch(product.sku);
                toast.success(`${product.name} added to the catalog.`);
              },
              onError: (error) => setFormError(error.message),
            });
          }}
        />
      </Modal>

      <Modal
        open={editing !== null}
        onClose={() => {
          setEditing(null);
          setFormError(null);
        }}
        title={editing ? `Edit ${editing.name}` : "Edit product"}
      >
        {editing ? (
          <ProductForm
            product={editing}
            categories={categories.data ?? []}
            unitLabel={store.unit_labels.default}
            productSchema={store.product_schema}
            busy={update.isPending}
            serverError={formError}
            onCancel={() => {
              setEditing(null);
              setFormError(null);
            }}
            onSubmit={(changes) => {
              setFormError(null);
              update.mutate(
                { id: editing.id, changes },
                {
                  onSuccess: (saved) => {
                    setEditing(null);
                    toast.success(`${saved.name} updated.`);
                  },
                  onError: (error) => setFormError(error.message),
                },
              );
            }}
          />
        ) : null}
      </Modal>

      {data?.total !== null && data?.total !== undefined ? (
        <p className="mt-4 text-xs text-ink-3">
          {count(data.total)} product{data.total === 1 ? "" : "s"} in this store.
        </p>
      ) : null}
    </>
  );
}
