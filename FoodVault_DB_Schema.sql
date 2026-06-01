CREATE TABLE user_profiles (
	id INTEGER NOT NULL, 
	supabase_user_id VARCHAR(128) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	name VARCHAR(255), 
	phone VARCHAR(64), 
	avatar_url VARCHAR(1024), 
	role VARCHAR(32) NOT NULL, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), auth_provider VARCHAR(64), last_login DATETIME, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_user_profiles_email ON user_profiles (email);
CREATE UNIQUE INDEX ix_user_profiles_supabase_user_id ON user_profiles (supabase_user_id);
CREATE INDEX ix_user_profiles_id ON user_profiles (id);
CREATE TABLE products (
	id INTEGER NOT NULL, 
	sku VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	price NUMERIC(10, 2) NOT NULL, 
	reserve_lock_price NUMERIC(10, 2), 
	lock_duration_days INTEGER, 
	delivery_options VARCHAR(255), 
	is_active BOOLEAN, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), metadata JSON DEFAULT '{}', slug VARCHAR(255), category VARCHAR(128), image VARCHAR(1024), stock_quantity INTEGER DEFAULT 0, inflation_savings NUMERIC(10, 2) DEFAULT 0, storage_type VARCHAR(64) DEFAULT 'pantry', locked_price NUMERIC(10, 2), feeds_people INTEGER DEFAULT 4, reserve_days INTEGER DEFAULT 30, rating NUMERIC(3, 1) DEFAULT 4.7, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_products_id ON products (id);
CREATE UNIQUE INDEX ix_products_sku ON products (sku);
CREATE TABLE admin_users (
	id INTEGER NOT NULL, 
	user_profile_id INTEGER NOT NULL, 
	is_superadmin BOOLEAN, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_profile_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);
CREATE INDEX ix_admin_users_id ON admin_users (id);
CREATE TABLE product_images (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	url VARCHAR(1024) NOT NULL, 
	is_primary BOOLEAN, 
	sort_order INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);
CREATE INDEX ix_product_images_id ON product_images (id);
CREATE TABLE inventory (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	reserved_quantity INTEGER NOT NULL, 
	incoming_quantity INTEGER NOT NULL, 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);
CREATE INDEX ix_inventory_id ON inventory (id);
CREATE TABLE carts (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);
CREATE INDEX ix_carts_id ON carts (id);
CREATE TABLE orders (
	id INTEGER NOT NULL, 
	order_number VARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	order_type VARCHAR(32) NOT NULL, 
	total_amount NUMERIC(12, 2) NOT NULL, 
	payment_status VARCHAR(32) NOT NULL, 
	delivery_date DATETIME, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);
CREATE INDEX ix_orders_id ON orders (id);
CREATE UNIQUE INDEX ix_orders_order_number ON orders (order_number);
CREATE TABLE reserve_vaults (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	total_value NUMERIC(12, 2) NOT NULL, 
	upfront_paid NUMERIC(12, 2) NOT NULL, 
	locked_until DATETIME, 
	next_delivery_date DATETIME, 
	health_score INTEGER, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);
CREATE INDEX ix_reserve_vaults_id ON reserve_vaults (id);
CREATE TABLE notifications (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	message TEXT NOT NULL, 
	type VARCHAR(64) NOT NULL, 
	is_read BOOLEAN, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);
CREATE INDEX ix_notifications_id ON notifications (id);
CREATE TABLE cart_items (
	id INTEGER NOT NULL, 
	cart_id INTEGER NOT NULL, 
	product_id INTEGER, 
	quantity INTEGER NOT NULL, 
	price_snapshot NUMERIC(10, 2) NOT NULL, 
	reserve_option VARCHAR(32) NOT NULL, 
	partial_delivery BOOLEAN, 
	lock_duration_days INTEGER, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(cart_id) REFERENCES carts (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE SET NULL
);
CREATE INDEX ix_cart_items_id ON cart_items (id);
CREATE TABLE order_items (
	id INTEGER NOT NULL, 
	order_id INTEGER NOT NULL, 
	product_id INTEGER, 
	quantity INTEGER NOT NULL, 
	unit_price NUMERIC(10, 2) NOT NULL, 
	total_price NUMERIC(12, 2) NOT NULL, 
	reserve_type VARCHAR(32) NOT NULL, 
	partial_delivery BOOLEAN, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE SET NULL
);
CREATE INDEX ix_order_items_id ON order_items (id);
CREATE TABLE payments (
	id INTEGER NOT NULL, 
	order_id INTEGER NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	currency VARCHAR(16) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	payment_method VARCHAR(64) NOT NULL, 
	transaction_ref VARCHAR(255), 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE CASCADE
);
CREATE INDEX ix_payments_id ON payments (id);
CREATE TABLE reserve_items (
	id INTEGER NOT NULL, 
	reserve_vault_id INTEGER NOT NULL, 
	product_id INTEGER, 
	quantity INTEGER NOT NULL, 
	unit_price NUMERIC(10, 2) NOT NULL, 
	deposit_paid NUMERIC(12, 2) NOT NULL, 
	reserve_type VARCHAR(32) NOT NULL, 
	partial_delivery BOOLEAN, 
	delivery_split JSON, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), metadata JSON DEFAULT '{}', 
	PRIMARY KEY (id), 
	FOREIGN KEY(reserve_vault_id) REFERENCES reserve_vaults (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE SET NULL
);
CREATE INDEX ix_reserve_items_id ON reserve_items (id);
CREATE TABLE delivery_schedules (
	id INTEGER NOT NULL, 
	reserve_item_id INTEGER NOT NULL, 
	scheduled_date DATETIME NOT NULL, 
	quantity INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	notes TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(reserve_item_id) REFERENCES reserve_items (id) ON DELETE CASCADE
);
CREATE INDEX ix_delivery_schedules_id ON delivery_schedules (id);
CREATE TABLE membership_plans (
	id INTEGER NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	code VARCHAR(64) NOT NULL, 
	price NUMERIC(12, 2) NOT NULL, 
	billing_period VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	benefits_json JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	UNIQUE (code)
);
CREATE INDEX ix_membership_plans_id ON membership_plans (id);
CREATE TABLE referral_codes (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	code VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	UNIQUE (code)
);
CREATE INDEX ix_referral_codes_id ON referral_codes (id);
CREATE TABLE referral_wallets (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	current_balance NUMERIC(12, 2) NOT NULL, 
	total_earned NUMERIC(12, 2) NOT NULL, 
	total_paid NUMERIC(12, 2) NOT NULL, 
	last_updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);
CREATE INDEX ix_referral_wallets_id ON referral_wallets (id);
CREATE TABLE wallets (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	balance NUMERIC(12, 2) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);
CREATE INDEX ix_wallets_id ON wallets (id);
CREATE TABLE product_prices (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	price NUMERIC(12, 2) NOT NULL, 
	country_code VARCHAR(8), 
	tier_name VARCHAR(64), 
	effective_from DATETIME, 
	effective_to DATETIME, 
	active BOOLEAN, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);
CREATE INDEX ix_product_prices_id ON product_prices (id);
CREATE TABLE currency_rates (
	id INTEGER NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	rate_to_usd NUMERIC(12, 6) NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	effective_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id)
);
CREATE INDEX ix_currency_rates_id ON currency_rates (id);
CREATE TABLE pricing_rules (
	id INTEGER NOT NULL, 
	rule_type VARCHAR(64) NOT NULL, 
	country_code VARCHAR(8), 
	currency VARCHAR(8), 
	membership_tier VARCHAR(32), 
	priority INTEGER, 
	discount_percent NUMERIC(5, 2), 
	reserve_lock_multiplier NUMERIC(5, 2), 
	time_window_start VARCHAR(16), 
	time_window_end VARCHAR(16), 
	effective_from DATETIME, 
	effective_to DATETIME, 
	is_active BOOLEAN, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id)
);
CREATE INDEX ix_pricing_rules_id ON pricing_rules (id);
CREATE TABLE reserve_sell_rules (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	reserve_vault_id INTEGER NOT NULL, 
	reserve_item_id INTEGER NOT NULL, 
	auto_sell_enabled BOOLEAN, 
	threshold_percent NUMERIC(5, 2) NOT NULL, 
	min_profit_amount NUMERIC(12, 2) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	FOREIGN KEY(reserve_vault_id) REFERENCES reserve_vaults (id) ON DELETE CASCADE, 
	FOREIGN KEY(reserve_item_id) REFERENCES reserve_items (id) ON DELETE CASCADE
);
CREATE INDEX ix_reserve_sell_rules_id ON reserve_sell_rules (id);
CREATE TABLE vault_market_prices (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	market_price NUMERIC(12, 2) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	effective_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);
CREATE INDEX ix_vault_market_prices_id ON vault_market_prices (id);
CREATE TABLE audit_logs (
	id INTEGER NOT NULL, 
	user_id INTEGER, 
	actor_role VARCHAR(32), 
	action VARCHAR(128) NOT NULL, 
	resource_type VARCHAR(128) NOT NULL, 
	resource_id VARCHAR(255), 
	message TEXT NOT NULL, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE SET NULL
);
CREATE INDEX ix_audit_logs_id ON audit_logs (id);
CREATE TABLE user_memberships (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	plan_id INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	effective_start DATETIME NOT NULL, 
	effective_end DATETIME NOT NULL, 
	auto_renew BOOLEAN, 
	renewal_count INTEGER, 
	last_renewed_at DATETIME, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	FOREIGN KEY(plan_id) REFERENCES membership_plans (id) ON DELETE CASCADE
);
CREATE INDEX ix_user_memberships_id ON user_memberships (id);
CREATE TABLE referral_usages (
	id INTEGER NOT NULL, 
	referral_code_id INTEGER NOT NULL, 
	referrer_id INTEGER NOT NULL, 
	referee_id INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	ip_hash VARCHAR(255), 
	used_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	metadata JSON, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_referral_usage_referee UNIQUE (referee_id), 
	FOREIGN KEY(referral_code_id) REFERENCES referral_codes (id) ON DELETE CASCADE, 
	FOREIGN KEY(referrer_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	FOREIGN KEY(referee_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);
CREATE INDEX ix_referral_usages_id ON referral_usages (id);
CREATE TABLE wallet_transactions (
	id INTEGER NOT NULL, 
	wallet_id INTEGER NOT NULL, 
	transaction_type VARCHAR(64) NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	idempotency_key VARCHAR(255) NOT NULL, 
	reference_id VARCHAR(255), 
	description TEXT, 
	source_type VARCHAR(64) NOT NULL, 
	source_id VARCHAR(255), 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	posted_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(wallet_id) REFERENCES wallets (id) ON DELETE CASCADE, 
	UNIQUE (idempotency_key)
);
CREATE INDEX ix_wallet_transactions_id ON wallet_transactions (id);
CREATE TABLE auto_sell_logs (
	id INTEGER NOT NULL, 
	reserve_item_id INTEGER NOT NULL, 
	rule_id INTEGER NOT NULL, 
	trigger_price NUMERIC(12, 2) NOT NULL, 
	current_price NUMERIC(12, 2) NOT NULL, 
	quantity_sold INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	error_message TEXT, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(reserve_item_id) REFERENCES reserve_items (id) ON DELETE CASCADE, 
	FOREIGN KEY(rule_id) REFERENCES reserve_sell_rules (id) ON DELETE CASCADE
);
CREATE INDEX ix_auto_sell_logs_id ON auto_sell_logs (id);
CREATE TABLE membership_transactions (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	membership_id INTEGER, 
	plan_id INTEGER NOT NULL, 
	transaction_type VARCHAR(64) NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	payment_method VARCHAR(64) NOT NULL, 
	reference_id VARCHAR(255) NOT NULL, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	FOREIGN KEY(membership_id) REFERENCES user_memberships (id) ON DELETE CASCADE, 
	FOREIGN KEY(plan_id) REFERENCES membership_plans (id) ON DELETE CASCADE, 
	UNIQUE (reference_id)
);
CREATE INDEX ix_membership_transactions_id ON membership_transactions (id);
CREATE TABLE membership_benefits (
	id INTEGER NOT NULL, 
	membership_id INTEGER NOT NULL, 
	benefit_key VARCHAR(128) NOT NULL, 
	benefit_value VARCHAR(255) NOT NULL, 
	enabled BOOLEAN, 
	notes TEXT, 
	active_from DATETIME, 
	active_to DATETIME, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(membership_id) REFERENCES user_memberships (id) ON DELETE CASCADE
);
CREATE INDEX ix_membership_benefits_id ON membership_benefits (id);
CREATE TABLE referral_commissions (
	id INTEGER NOT NULL, 
	usage_id INTEGER NOT NULL, 
	order_id INTEGER, 
	amount NUMERIC(12, 2) NOT NULL, 
	eligible_amount NUMERIC(12, 2) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	approval_notes TEXT, 
	wallet_transaction_id INTEGER, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(usage_id) REFERENCES referral_usages (id) ON DELETE CASCADE, 
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE SET NULL, 
	FOREIGN KEY(wallet_transaction_id) REFERENCES wallet_transactions (id) ON DELETE SET NULL
);
CREATE INDEX ix_referral_commissions_id ON referral_commissions (id);
CREATE TABLE ledger_entries (
	id INTEGER NOT NULL, 
	wallet_id INTEGER NOT NULL, 
	transaction_id INTEGER NOT NULL, 
	account_type VARCHAR(64) NOT NULL, 
	direction VARCHAR(16) NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	balance_after NUMERIC(12, 2) NOT NULL, 
	memo TEXT, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(wallet_id) REFERENCES wallets (id) ON DELETE CASCADE, 
	FOREIGN KEY(transaction_id) REFERENCES wallet_transactions (id) ON DELETE CASCADE
);
CREATE INDEX ix_ledger_entries_id ON ledger_entries (id);
CREATE TABLE profit_distribution (
	id INTEGER NOT NULL, 
	reserve_item_id INTEGER NOT NULL, 
	auto_sell_log_id INTEGER NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	wallet_transaction_id INTEGER, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(reserve_item_id) REFERENCES reserve_items (id) ON DELETE CASCADE, 
	FOREIGN KEY(auto_sell_log_id) REFERENCES auto_sell_logs (id) ON DELETE CASCADE, 
	FOREIGN KEY(wallet_transaction_id) REFERENCES wallet_transactions (id) ON DELETE SET NULL
);
CREATE INDEX ix_profit_distribution_id ON profit_distribution (id);
CREATE TABLE stripe_customers (
	id UUID NOT NULL, 
	user_id INTEGER NOT NULL, 
	stripe_customer_id VARCHAR(128) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	UNIQUE (stripe_customer_id)
);
CREATE TABLE payment_transactions (
	id UUID NOT NULL, 
	payment_id INTEGER NOT NULL, 
	stripe_payment_intent_id VARCHAR(128) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	payment_method VARCHAR(64), 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(payment_id) REFERENCES payments (id) ON DELETE CASCADE, 
	UNIQUE (stripe_payment_intent_id)
);
CREATE TABLE subscriptions (
	id UUID NOT NULL, 
	user_id INTEGER NOT NULL, 
	stripe_subscription_id VARCHAR(128) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	plan_id INTEGER, 
	current_period_start DATETIME, 
	current_period_end DATETIME, 
	cancel_at_period_end BOOLEAN, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	UNIQUE (stripe_subscription_id), 
	FOREIGN KEY(plan_id) REFERENCES membership_plans (id) ON DELETE SET NULL
);
CREATE TABLE stripe_webhook_events (
	id UUID NOT NULL, 
	event_id VARCHAR(128) NOT NULL, 
	event_type VARCHAR(64) NOT NULL, 
	payload JSON, 
	processed BOOLEAN, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	UNIQUE (event_id)
);
CREATE TABLE financial_ledger (
	id UUID NOT NULL, 
	user_id INTEGER, 
	wallet_id INTEGER, 
	transaction_id UUID, 
	entry_type VARCHAR(32) NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	memo VARCHAR(255), 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	FOREIGN KEY(wallet_id) REFERENCES wallets (id) ON DELETE SET NULL
);
CREATE TABLE invoices (
	id UUID NOT NULL, 
	user_id INTEGER NOT NULL, 
	order_id INTEGER, 
	stripe_invoice_id VARCHAR(128) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	amount_due NUMERIC(12, 2) NOT NULL, 
	amount_paid NUMERIC(12, 2) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	due_date DATETIME, 
	paid_at DATETIME, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE SET NULL, 
	UNIQUE (stripe_invoice_id)
);
CREATE TABLE subscription_events (
	id UUID NOT NULL, 
	subscription_id UUID NOT NULL, 
	event_type VARCHAR(64) NOT NULL, 
	event_id VARCHAR(128) NOT NULL, 
	payload JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(subscription_id) REFERENCES subscriptions (id) ON DELETE CASCADE
);
CREATE TABLE admin_sessions (
	id INTEGER NOT NULL, 
	admin_user_id INTEGER NOT NULL, 
	token_hash VARCHAR(255) NOT NULL, 
	jti VARCHAR(128) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	ip_address VARCHAR(64), 
	user_agent VARCHAR(512), 
	expires_at DATETIME, 
	revoked_at DATETIME, 
	last_seen_at DATETIME, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(admin_user_id) REFERENCES admin_users (id) ON DELETE CASCADE, 
	UNIQUE (token_hash), 
	UNIQUE (jti)
);
CREATE INDEX ix_admin_sessions_id ON admin_sessions (id);
CREATE TABLE reserve_analytics (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	metrics JSON, 
	period_start DATETIME, 
	period_end DATETIME, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);
CREATE INDEX ix_reserve_analytics_id ON reserve_analytics (id);
CREATE TABLE inventory_tracking (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	reserved_quantity INTEGER NOT NULL, 
	snapshot_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);
CREATE INDEX ix_inventory_tracking_id ON inventory_tracking (id);
CREATE TABLE reserve_activity_logs (
	id INTEGER NOT NULL, 
	user_id INTEGER, 
	action VARCHAR(128) NOT NULL, 
	resource VARCHAR(128), 
	details JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE SET NULL
);
CREATE INDEX ix_reserve_activity_logs_id ON reserve_activity_logs (id);
CREATE TABLE reserve_positions (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	product_id INTEGER, 
	reserve_vault_id INTEGER, 
	reserved_quantity INTEGER NOT NULL, 
	locked_price NUMERIC(12, 2) NOT NULL, 
	total_value NUMERIC(12, 2) NOT NULL, 
	deposit_paid NUMERIC(12, 2) NOT NULL, 
	ownership_percent INTEGER NOT NULL, 
	remaining_balance NUMERIC(12, 2) NOT NULL, 
	lock_expires_at DATETIME, 
	status VARCHAR(32) NOT NULL, 
	metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_profiles (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE SET NULL, 
	FOREIGN KEY(reserve_vault_id) REFERENCES reserve_vaults (id) ON DELETE SET NULL
);
CREATE INDEX ix_reserve_positions_id ON reserve_positions (id);
