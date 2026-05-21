-- TPC-H Integrity Constraints for PostgreSQL
-- Run this AFTER data is fully loaded (faster bulk load without constraints)
-- Source: TPC-H Specification v3.0.1 (dss.ri), adapted for PostgreSQL

-- Primary keys
ALTER TABLE region     ADD PRIMARY KEY (r_regionkey);
ALTER TABLE nation     ADD PRIMARY KEY (n_nationkey);
ALTER TABLE supplier   ADD PRIMARY KEY (s_suppkey);
ALTER TABLE part       ADD PRIMARY KEY (p_partkey);
ALTER TABLE partsupp   ADD PRIMARY KEY (ps_partkey, ps_suppkey);
ALTER TABLE customer   ADD PRIMARY KEY (c_custkey);
ALTER TABLE orders     ADD PRIMARY KEY (o_orderkey);
ALTER TABLE lineitem   ADD PRIMARY KEY (l_orderkey, l_linenumber);

-- Foreign keys
ALTER TABLE nation    ADD FOREIGN KEY (n_regionkey)            REFERENCES region(r_regionkey);
ALTER TABLE supplier  ADD FOREIGN KEY (s_nationkey)            REFERENCES nation(n_nationkey);
ALTER TABLE customer  ADD FOREIGN KEY (c_nationkey)            REFERENCES nation(n_nationkey);
ALTER TABLE partsupp  ADD FOREIGN KEY (ps_partkey)             REFERENCES part(p_partkey);
ALTER TABLE partsupp  ADD FOREIGN KEY (ps_suppkey)             REFERENCES supplier(s_suppkey);
ALTER TABLE orders    ADD FOREIGN KEY (o_custkey)              REFERENCES customer(c_custkey);
ALTER TABLE lineitem  ADD FOREIGN KEY (l_orderkey)             REFERENCES orders(o_orderkey);
ALTER TABLE lineitem  ADD FOREIGN KEY (l_partkey, l_suppkey)   REFERENCES partsupp(ps_partkey, ps_suppkey);

-- Recommended indexes for analytical queries
CREATE INDEX idx_lineitem_shipdate    ON lineitem(l_shipdate);
CREATE INDEX idx_lineitem_orderkey    ON lineitem(l_orderkey);
CREATE INDEX idx_orders_orderdate     ON orders(o_orderdate);
CREATE INDEX idx_orders_custkey       ON orders(o_custkey);
CREATE INDEX idx_customer_nationkey   ON customer(c_nationkey);
CREATE INDEX idx_supplier_nationkey   ON supplier(s_nationkey);
