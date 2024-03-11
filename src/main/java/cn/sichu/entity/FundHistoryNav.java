package cn.sichu.entity;

import java.util.Date;

/**
 * fund_history_nav
 *
 * @author sichu huang
 * @date 2024/03/11
 **/
public class FundHistoryNav {

    private Long id;
    private String code;
    private Date navDate;
    private String nav;

    public FundHistoryNav() {
    }

    public FundHistoryNav(Long id, String code, Date navDate, String nav) {
        this.id = id;
        this.code = code;
        this.navDate = navDate;
        this.nav = nav;
    }

    @Override
    public String toString() {
        return "FundHistoryNav{" + "id=" + id + ", code='" + code + '\'' + ", navDate=" + navDate + ", nav='" + nav
            + '\'' + '}';
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public Date getNavDate() {
        return navDate;
    }

    public void setNavDate(Date navDate) {
        this.navDate = navDate;
    }

    public String getNav() {
        return nav;
    }

    public void setNav(String nav) {
        this.nav = nav;
    }
}
