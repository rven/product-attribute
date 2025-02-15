# Copyright 2017 Tecnativa - Carlos Dauden
# Copyright 2018 Tecnativa - David Vidal
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from collections import defaultdict

from odoo import _, api, fields, models
from odoo.osv import expression
from odoo.exceptions import ValidationError

from odoo.tools.misc import formatLang


class ProductPricelistPrint(models.TransientModel):
    _name = 'product.pricelist.print'
    _description = 'Product Pricelist Print'

    pricelist_id = fields.Many2one(
        comodel_name='product.pricelist',
        string='Pricelist',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
    )
    partner_ids = fields.Many2many(
        comodel_name='res.partner',
        string='Customers',
    )
    categ_ids = fields.Many2many(
        comodel_name='product.category',
        string='Categories',
    )
    show_only_defined_products = fields.Boolean(
        string='Show the products defined on pricelist',
        help='Check this field to print only the products defined in the pricelist. '
             'The entries in the list referring to all products will not be displayed.',
    )
    show_variants = fields.Boolean()
    product_tmpl_ids = fields.Many2many(
        comodel_name='product.template',
        string='Product Templates',
        help='Keep empty for all products',
    )
    product_ids = fields.Many2many(
        comodel_name='product.product',
        string='Products',
        help='Keep empty for all products',
    )
    vat_mode = fields.Selection(selection=[
        ("vat_excl", "Vat Excluded"),
        ("vat_incl", "Vat Included"),
    ])
    show_product_uom = fields.Boolean(string='Show Product UoM')
    show_standard_price = fields.Boolean(string='Show Cost Price')
    show_sale_price = fields.Boolean(string='Show Sale Price')
    hide_pricelist_name = fields.Boolean(string='Hide Pricelist Name')
    order_field = fields.Selection([
        ('name', 'Name'),
        ('default_code', 'Internal Reference'),
    ], string='Order')
    group_field_id = fields.Many2one(
        comodel_name="ir.model.fields",
        required=True,
        domain=[
            ("model", "=", "product.product"),
            ("ttype", "=", "many2one"),
        ],
        default=lambda x: x._default_group_field_id())
    partner_count = fields.Integer(
        compute='_compute_partner_count'
    )
    date = fields.Date()
    last_ordered_products = fields.Integer(
        help="If you enter an X number here, then, for each selected customer,"
             " the last X ordered products will be obtained for the report."
    )
    summary = fields.Text(string="Summary")

    @api.multi
    @api.depends('partner_ids')
    def _compute_partner_count(self):
        for record in self:
            self.partner_count = len(record.partner_ids)

    @api.onchange('partner_ids')
    def _onchange_partner_ids(self):
        if not self.partner_count:
            self.last_ordered_products = False

    @api.model
    def default_get(self, fields):
        res = super(ProductPricelistPrint, self).default_get(fields)
        if self.env.context.get('active_model') == 'product.template':
            res['product_tmpl_ids'] = [
                (6, 0, self.env.context.get('active_ids', []))]
        elif self.env.context.get('active_model') == 'product.product':
            res['show_variants'] = True
            res['product_ids'] = [
                (6, 0, self.env.context.get('active_ids', []))]
        elif self.env.context.get('active_model') == 'product.pricelist':
            res['pricelist_id'] = self.env.context.get('active_id', False)
        elif self.env.context.get('active_model') == 'res.partner':
            active_ids = self.env.context.get('active_ids', [])
            res['partner_ids'] = [(6, 0, active_ids)]
            if len(active_ids) == 1:
                partner = self.env['res.partner'].browse(active_ids[0])
                res['pricelist_id'] = partner.property_product_pricelist.id
        elif self.env.context.get('active_model') == 'product.pricelist.item':
            active_ids = self.env.context.get('active_ids', [])
            items = self.env['product.pricelist.item'].browse(active_ids)
            # Set pricelist if all the items belong to the same one
            if len(items.mapped('pricelist_id')) == 1:
                res['pricelist_id'] = items[0].pricelist_id.id
            product_items = items.filtered(
                lambda x: x.applied_on == '0_product_variant')
            template_items = items.filtered(
                lambda x: x.applied_on == '1_product')
            category_items = items.filtered(
                lambda x: x.applied_on == '2_product_category')
            # Convert al pricelist items to their affected variants
            if product_items:
                res['show_variants'] = True
                product_ids = product_items.mapped('product_id')
                product_ids |= template_items.mapped(
                    'product_tmpl_id.product_variant_ids')
                product_ids |= product_ids.search([
                    ('sale_ok', '=', True),
                    ('categ_id', 'in', category_items.mapped('categ_id').ids)
                ])
                res['product_ids'] = [(6, 0, product_ids.ids)]
            # Convert al pricelist items to their affected templates
            if template_items and not product_items:
                product_tmpl_ids = template_items.mapped('product_tmpl_id')
                product_tmpl_ids |= product_tmpl_ids.search([
                    ('sale_ok', '=', True),
                    ('categ_id', 'in', category_items.mapped('categ_id').ids)
                ])
                res['product_tmpl_ids'] = [
                    (6, 0, product_tmpl_ids.ids)]
            # Only category items, we just set the categories
            if category_items and not product_items and not template_items:
                res['categ_ids'] = [
                    (6, 0, category_items.mapped('categ_id').ids)]
        return res

    def _default_group_field_id(self):
        IrModelFields = self.env["ir.model.fields"]
        return IrModelFields.search([
            ("model", "=", "product.product"),
            ("name", "=", "categ_id"),
        ])

    @api.multi
    def print_report(self):
        if not(self.pricelist_id or self.partner_count
               or self.show_standard_price or self.show_sale_price):
            raise ValidationError(_(
                'You must set price list or any customer '
                'or any show price option.'))
        return self.env.ref(
            'product_pricelist_direct_print.'
            'action_report_product_pricelist').report_action(self)

    @api.multi
    def action_pricelist_send(self):
        self.ensure_one()
        if self.partner_count > 1:
            self.send_batch()
        else:
            if self.partner_count == 1:
                partner = self.partner_ids[0]
                self.write({
                    'partner_id': partner.id,
                    'pricelist_id': partner.property_product_pricelist.id,
                })
            return self.message_composer_action()

    @api.multi
    def message_composer_action(self):
        self.ensure_one()

        template_id = self.env.ref(
            'product_pricelist_direct_print.email_template_edi_pricelist').id
        compose_form_id = self.env.ref(
            'mail.email_compose_message_wizard_form').id
        ctx = {
            'default_composition_mode': 'comment',
            'default_res_id': self.id,
            'default_model': 'product.pricelist.print',
            'default_use_template': bool(template_id),
            'default_template_id': template_id,
        }
        return {
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'view_id': compose_form_id,
            'target': 'new',
            'context': ctx,
        }

    @api.multi
    def send_batch(self):
        self.ensure_one()
        for partner in self.partner_ids.filtered(lambda x: not x.parent_id):
            self.write({
                'partner_id': partner.id,
                'pricelist_id': partner.property_product_pricelist.id,
            })
            self.force_pricelist_send()

    @api.multi
    def force_pricelist_send(self):
        template_id = self.env.ref(
            'product_pricelist_direct_print.email_template_edi_pricelist').id
        composer = self.env['mail.compose.message'].with_context({
            'default_composition_mode': 'mass_mail',
            'default_notify': True,
            'default_res_id': self.id,
            'default_model': 'product.pricelist.print',
            'default_template_id': template_id,
            'active_ids': self.ids,
        }).create({})
        values = composer.onchange_template_id(
            template_id, 'mass_mail', 'product.pricelist.print',
            self.id)['value']
        composer.write(values)
        composer.send_mail()

    @api.multi
    def get_last_ordered_products_to_print(self):
        self.ensure_one()
        partner = self.partner_id
        if not partner and self.partner_count == 1:
            partner = self.partner_ids[0]
        orders = partner.sale_order_ids.filtered(
            lambda r: r.state not in ['draft', 'sent', 'cancel'])
        orders = orders.sorted(key=lambda r: r.confirmation_date, reverse=True)
        products = orders.mapped(
            'order_line').mapped('product_id').filtered('active')
        return products[:self.last_ordered_products]

    @api.multi
    def get_pricelist_to_print(self):
        self.ensure_one()
        pricelist = self.pricelist_id
        if not pricelist and self.partner_count == 1:
            pricelist = self.partner_ids[0].property_product_pricelist
        return pricelist

    def get_products_domain(self):
        domain = [
            ('sale_ok', '=', True)
        ]
        if self.show_only_defined_products:
            aux_domain = []
            items_dic = {"categ_ids": [], "product_ids": [], "variant_ids": []}
            for item in self.pricelist_id.item_ids:
                if item.applied_on == "0_product_variant":
                    items_dic["variant_ids"].append(item.product_id.id)
                if item.applied_on == "1_product":
                    items_dic["product_ids"].append(item.product_tmpl_id.id)
                if item.applied_on == "2_product_category" and item.categ_id.parent_id:
                    items_dic["categ_ids"].append(item.categ_id.id)
            if items_dic["categ_ids"]:
                aux_domain = expression.OR([
                    aux_domain,
                    [('categ_id', 'in', items_dic["categ_ids"])]
                ])
            if items_dic["product_ids"]:
                if self.show_variants:
                    aux_domain = expression.OR([
                        aux_domain,
                        [('product_tmpl_id', 'in', items_dic["product_ids"])]
                    ])
                else:
                    aux_domain = expression.OR([
                        aux_domain,
                        [('id', 'in', items_dic["product_ids"])]
                    ])
            if items_dic["variant_ids"]:
                if self.show_variants:
                    aux_domain = expression.OR([
                        aux_domain,
                        [('id', 'in', items_dic["variant_ids"])]
                    ])
                else:
                    aux_domain = expression.OR([
                        aux_domain,
                        [('product_variant_ids', 'in', items_dic["variant_ids"])]
                    ])
            domain = expression.AND([domain, aux_domain])
        if self.categ_ids:
            domain = expression.AND([domain, [('categ_id', 'in', self.categ_ids.ids)]])
        return domain

    def get_products_to_print(self):
        self.ensure_one()
        if self.last_ordered_products:
            products = self.get_last_ordered_products_to_print()
        else:
            if self.show_variants:
                products = self.product_ids or self.product_tmpl_ids.mapped(
                    'product_variant_ids')
            else:
                products = self.product_tmpl_ids
        if not products:
            products = products.search(self.get_products_domain())
        return products

    def get_group_key(self, product):
        group_field = getattr(product, self.group_field_id.name)
        return getattr(
            group_field, "complete_name", getattr(group_field, "name")
        ) or _("Undefined")

    def get_sorted_products(self, products):
        if self.order_field:
            # Using "or ''" to avoid issues with None type
            return products.sorted(
                lambda x: getattr(x, self.order_field) or '')
        return products

    def get_groups_to_print(self):
        self.ensure_one()
        products = self.get_products_to_print()
        if not products:
            return []
        group_dict = defaultdict(lambda: products.browse())
        for product in products:
            key = self.get_group_key(product)
            group_dict[key] |= product
        group_list = []
        for key in sorted(group_dict.keys()):
            group_list.append({
                'group_name': key,
                'products': self.get_sorted_products(group_dict[key])
            })
        return group_list

    def export_xlsx(self):
        self.ensure_one()
        return self.env.ref(
            'product_pricelist_direct_print.product_pricelist_xlsx').report_action(self)

    def compute_pricelist_price(self, product, display_currency=True):
        self.ensure_one()
        price = product.with_context(
            pricelist=self.get_pricelist_to_print().id, date=self.date
        ).price

        if self.vat_mode == "vat_excl":
            price = product.taxes_id.compute_all(price)["total_excluded"]
        elif self.vat_mode == "vat_incl":
            price = product.taxes_id.compute_all(price)["total_included"]

        if display_currency:
            return formatLang(
                self.env, price, currency_obj=self.get_pricelist_to_print().currency_id
            )
        else:
            return price
